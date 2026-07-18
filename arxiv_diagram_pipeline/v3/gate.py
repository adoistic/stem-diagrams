"""Local diagram gate: frozen SigLIP2 embedding + logistic regression.

Loads once, classifies PIL crops in batches on MPS/CPU. Returns the predicted
class and P(diagram); the caller keeps crops the gate calls a diagram.
"""

import pickle
from pathlib import Path

import numpy as np
import torch

_STATE = {"clf": None, "model": None, "processor": None, "device": None,
          "classes": None}
PKL = Path(__file__).resolve().parent / "gate_logreg.pkl"


def _lazy_load():
    if _STATE["clf"] is not None:
        return
    import os
    from transformers import AutoModel, AutoProcessor
    d = pickle.loads(PKL.read_bytes())
    _STATE["clf"] = d["clf"]
    _STATE["classes"] = d["classes"]
    device = os.getenv("GATE_DEVICE") or (
        "mps" if torch.backends.mps.is_available() else "cpu")
    _STATE["device"] = device
    _STATE["model"] = AutoModel.from_pretrained(d["backbone"]).to(device).eval()
    _STATE["processor"] = AutoProcessor.from_pretrained(d["backbone"])


@torch.no_grad()
def _embed(pil_images):
    proc = _STATE["processor"](images=pil_images, return_tensors="pt")
    proc = {k: v.to(_STATE["device"]) for k, v in proc.items()}
    feats = _STATE["model"].get_image_features(**proc)
    if not torch.is_tensor(feats):
        feats = feats.pooler_output if hasattr(feats, "pooler_output") else feats[0]
    feats = torch.nn.functional.normalize(feats, dim=-1)
    return feats.cpu().numpy()


def classify(pil_images, batch_size=32):
    """Return list of (predicted_class, p_diagram) for each PIL image."""
    _lazy_load()
    out = []
    clf = _STATE["clf"]
    diag_idx = _STATE["classes"].index("diagram")
    for i in range(0, len(pil_images), batch_size):
        chunk = pil_images[i:i + batch_size]
        X = _embed(chunk)
        proba = clf.predict_proba(X)
        preds = proba.argmax(1)
        for p, pr in zip(preds, proba):
            out.append((_STATE["classes"][p], float(pr[diag_idx])))
    return out


def is_diagram(pil_images, threshold=0.5, batch_size=32):
    """Bool per image: accept as a proper diagram.

    Accept when argmax is 'diagram'. threshold gives an optional precision dial:
    require P(diagram) >= threshold as well (0.5 = argmax only for the binary).
    """
    res = classify(pil_images, batch_size)
    return [(cls == "diagram" and p >= threshold) for cls, p in res]
