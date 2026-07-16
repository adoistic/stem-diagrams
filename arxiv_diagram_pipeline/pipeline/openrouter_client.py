"""Minimal OpenRouter chat-completions client with retries and JSON extraction."""

import json
import logging
import re
import time

import requests

import config

log = logging.getLogger(__name__)

RETRYABLE_STATUS = (429, 500, 502, 503, 504)

# Models that rejected the reasoning parameter at runtime — tracked per model
# so one provider's rejection doesn't disable it for the others.
_reasoning_rejected = set()


class MissingAPIKeyError(RuntimeError):
    pass


class CreditsExhaustedError(RuntimeError):
    """OpenRouter returned 402 — account credits are used up. Not retryable;
    the pipeline should save state and stop cleanly."""


def _reasoning_payload(model):
    effort = (config.REASONING_EFFORT or "").lower()
    if model in _reasoning_rejected or effort in ("", "default"):
        return None
    if effort == "none":
        return {"enabled": False}
    return {"effort": effort}


def chat_with_meta(messages, retries=4, model=None):
    """Send a chat request; returns (reply_text, cost_usd).

    Deliberately no max_tokens: reasoning models burn an explicit budget on
    hidden reasoning and then return empty content. The provider default
    output limit is the right ceiling.
    """
    if not config.OPENROUTER_API_KEY:
        raise MissingAPIKeyError("OPENROUTER_API_KEY is empty — fill it in .env")

    model = model or config.OPENROUTER_MODEL
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, retries + 1):
        payload = {
            "model": model,
            "messages": messages,
            "usage": {"include": True},
        }
        reasoning = _reasoning_payload(model)
        if reasoning:
            payload["reasoning"] = reasoning
        try:
            resp = requests.post(
                config.OPENROUTER_URL, json=payload, headers=headers, timeout=180
            )
            if resp.status_code == 402:
                raise CreditsExhaustedError(
                    f"OpenRouter credits exhausted (HTTP 402): {resp.text[:200]}")
            if resp.status_code == 400 and reasoning and "reasoning" in resp.text.lower():
                # This provider doesn't accept the reasoning parameter — drop
                # it for this model for the rest of the run and retry now.
                log.warning("%s rejected reasoning param; disabling it. (%s)",
                            model, resp.text[:150])
                _reasoning_rejected.add(model)
                continue
            if resp.status_code >= 400 and resp.status_code not in RETRYABLE_STATUS:
                raise requests.HTTPError(
                    f"HTTP {resp.status_code} (non-retryable): {resp.text[:300]}"
                )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise requests.HTTPError(f"OpenRouter error: {data['error']}")
            content = data["choices"][0]["message"]["content"]
            if not content:
                # Reasoning models occasionally return null content (e.g. the
                # provider-side output cap was hit mid-reasoning).
                finish = data["choices"][0].get("finish_reason")
                raise requests.HTTPError(
                    f"empty content (finish_reason={finish})"
                )
            cost = float((data.get("usage") or {}).get("cost") or 0.0)
            return content, cost
        except (CreditsExhaustedError, MissingAPIKeyError):
            raise
        except requests.HTTPError as exc:
            if "non-retryable" in str(exc) or attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("OpenRouter call failed (%s); retry %d/%d in %ds",
                        exc, attempt, retries, wait)
            time.sleep(wait)
        except (requests.RequestException, KeyError, ValueError) as exc:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            log.warning("OpenRouter call failed (%s); retry %d/%d in %ds",
                        exc, attempt, retries, wait)
            time.sleep(wait)


def chat(messages, retries=4, model=None):
    """Send a chat request to the configured OpenRouter model, return reply text."""
    content, _cost = chat_with_meta(messages, retries=retries, model=model)
    return content


def extract_json(text):
    """Parse a JSON object out of an LLM reply (tolerates ```json fences and prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object in LLM reply: {text[:200]!r}")
    # strict=False tolerates raw control characters (literal newlines/tabs)
    # inside string values — a common LLM formatting slip when writing
    # multi-paragraph text into a JSON string instead of escaping "\n".
    decoder = json.JSONDecoder(strict=False)
    try:
        obj, _ = decoder.raw_decode(text[start:])
    except ValueError:
        # Second common slip: raw LaTeX in string values ("\alpha", "\mathrm")
        # — invalid JSON escapes. Double every backslash that doesn't start a
        # valid escape sequence, then parse again.
        repaired = re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", text[start:])
        obj, _ = decoder.raw_decode(repaired)
    return obj
