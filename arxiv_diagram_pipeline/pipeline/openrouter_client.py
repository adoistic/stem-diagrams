"""Minimal OpenRouter chat-completions client with retries and JSON extraction."""

import json
import logging
import re
import time

import requests

import config

log = logging.getLogger(__name__)

RETRYABLE_STATUS = (429, 500, 502, 503, 504)


class MissingAPIKeyError(RuntimeError):
    pass


def chat(messages, max_tokens=2000, retries=4):
    """Send a chat request to the configured OpenRouter model, return reply text."""
    if not config.OPENROUTER_API_KEY:
        raise MissingAPIKeyError("OPENROUTER_API_KEY is empty — fill it in .env")

    payload = {
        "model": config.OPENROUTER_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                config.OPENROUTER_URL, json=payload, headers=headers, timeout=180
            )
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
                # Reasoning models can burn the whole max_tokens budget on the
                # hidden "reasoning" field and return null content.
                finish = data["choices"][0].get("finish_reason")
                raise requests.HTTPError(
                    f"empty content (finish_reason={finish}) — likely ran out of "
                    "max_tokens before producing a reply"
                )
            return content
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
    obj, _ = json.JSONDecoder(strict=False).raw_decode(text[start:])
    return obj
