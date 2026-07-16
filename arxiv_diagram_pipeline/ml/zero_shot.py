#!/usr/bin/env python3
"""Approach B: zero-shot classification with SigLIP2 text prompts.

Uses the cached image embeddings (siglip2 backbone) and scores them against
class text prompts — no training at all. Validation metrics only.
"""

import logging

import numpy as np
import torch

import common

log = logging.getLogger("zeroshot")

MODEL_NAME = "google/siglip2-base-patch16-224"

PROMPTS = {
    "diagram": [
        "a technical block diagram from an engineering paper",
        "a circuit schematic diagram",
        "a flowchart or system architecture diagram",
        "a labeled schematic illustration of an experimental setup",
    ],
    "data_plot": [
        "a line chart of experimental results",
        "a scatter plot with axes and data points",
        "a heatmap or colormap of measured data",
        "a bar chart of results",
    ],
    "photo": [
        "a photograph of laboratory equipment",
        "a microscope image of a material sample",
    ],
    "fragment_junk": [
        "a blank or nearly empty image",
        "a small cropped fragment of a figure, such as a lone axis or legend",
        "a text snippet or equation from a paper",
    ],
}


def text_features():
    from transformers import AutoModel, AutoProcessor
    model = AutoModel.from_pretrained(MODEL_NAME)
    processor = AutoProcessor.from_pretrained(MODEL_NAME)
    feats = []
    with torch.no_grad():
        for cls in common.CLASSES:
            inputs = processor(text=PROMPTS[cls], padding="max_length",
                               return_tensors="pt")
            t = model.get_text_features(**inputs)
            if not torch.is_tensor(t):
                # transformers 5.x wraps the features in a ModelOutput
                t = t.pooler_output if hasattr(t, "pooler_output") else t[0]
            t = torch.nn.functional.normalize(t, dim=-1).mean(0)
            feats.append(torch.nn.functional.normalize(t, dim=-1).numpy())
    return np.stack(feats)  # 4 x D


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    rows = common.load_crops_manifest()
    ids, emb = common.load_embeddings("siglip2")
    kept, X, y4, is_diag, split = common.align(rows, ids, emb)
    T = text_features()
    scores = X @ T.T                     # cosine (both sides unit-norm)
    pred4 = scores.argmax(1)
    prob4 = np.exp(scores * 10) / np.exp(scores * 10).sum(1, keepdims=True)

    va, te = split == "val", split == "test"
    m = common.binary_metrics(is_diag[va], (pred4[va] == 0).astype(int))
    m["acc4"] = round(float((pred4[va] == y4[va]).mean()), 4)
    common.save_predictions("zeroshot_siglip2", "val",
                            [r["image_id"] for r, k in zip(kept, va) if k],
                            pred4[va], prob4[va])
    common.save_predictions("zeroshot_siglip2", "test",
                            [r["image_id"] for r, k in zip(kept, te) if k],
                            pred4[te], prob4[te])
    common.record_result("zeroshot_siglip2", "zero-shot",
                         {"model": MODEL_NAME, "prompts_per_class":
                          {k: len(v) for k, v in PROMPTS.items()}},
                         m, notes=f"4cls-val-acc {m['acc4']}")
    log.info("zero-shot val: binary acc %.4f f1 %.4f (4cls %.4f)",
             m["acc"], m["f1"], m["acc4"])


if __name__ == "__main__":
    main()
