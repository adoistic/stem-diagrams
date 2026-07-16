#!/usr/bin/env python3
"""Approach D: fine-tune a small timm model end-to-end on the 4-class crops.

Default efficientnet_b0 @224 on MPS. Reports validation metrics; saves test
predictions and the best checkpoint (by val binary F1).
"""

import argparse
import logging
import time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

import common

log = logging.getLogger("finetune")


class CropDataset(Dataset):
    def __init__(self, rows, transform):
        self.rows = rows
        self.transform = transform

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        try:
            with Image.open(r["path"]) as im:
                x = self.transform(im.convert("RGB"))
        except Exception:
            x = torch.zeros(3, 224, 224)
        return x, common.CLS_TO_IDX[r["cls"]], r["image_id"]


def make_transforms(train):
    from torchvision import transforms as T
    aug = [T.Resize((224, 224))]
    if train:
        aug += [T.RandomAffine(degrees=3, translate=(0.02, 0.02),
                               scale=(0.95, 1.05), fill=255),
                T.ColorJitter(brightness=0.15, contrast=0.15)]
    aug += [T.ToTensor(),
            T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])]
    return T.Compose(aug)


@torch.no_grad()
def predict(model, loader, device):
    model.eval()
    probs, ids = [], []
    for x, _y, iid in loader:
        p = F.softmax(model(x.to(device)), dim=1).cpu().numpy()
        probs.append(p)
        ids.extend(int(i) for i in iid)
    return np.concatenate(probs), np.array(ids)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="efficientnet_b0.ra_in1k")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    torch.manual_seed(0)

    import timm
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    rows = common.load_crops_manifest()
    tr = [r for r in rows if r["split"] == "train"]
    va = [r for r in rows if r["split"] == "val"]
    te = [r for r in rows if r["split"] == "test"]

    counts = np.bincount([common.CLS_TO_IDX[r["cls"]] for r in tr],
                         minlength=4).astype(np.float32)
    weights = torch.tensor((counts.sum() / np.maximum(counts, 1)) ** 0.5,
                           device=device)

    model = timm.create_model(args.model, pretrained=True, num_classes=4)
    model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, T_max=args.epochs * (len(tr) // args.batch + 1))

    dl_tr = DataLoader(CropDataset(tr, make_transforms(True)), args.batch,
                       shuffle=True, num_workers=4, persistent_workers=True)
    dl_va = DataLoader(CropDataset(va, make_transforms(False)), 64,
                       num_workers=4)
    dl_te = DataLoader(CropDataset(te, make_transforms(False)), 64,
                       num_workers=4)

    y4_va = np.array([common.CLS_TO_IDX[r["cls"]] for r in va])
    best = {"f1": -1}
    name = f"finetune_{args.model.split('.')[0]}"
    ckpt_path = common.ML_DIR / "cache" / f"{name}.pt"
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        running = 0.0
        for step, (x, y, _iid) in enumerate(dl_tr):
            opt.zero_grad()
            loss = F.cross_entropy(model(x.to(device)), y.to(device),
                                   weight=weights)
            loss.backward()
            opt.step()
            sched.step()
            running += float(loss)
            if step % 20 == 0:
                log.info("epoch %d step %d/%d loss %.3f",
                         epoch, step, len(dl_tr), running / (step + 1))
        prob_va, _ = predict(model, dl_va, device)
        pred_va = prob_va.argmax(1)
        m = common.binary_metrics((y4_va == 0).astype(int),
                                  (pred_va == 0).astype(int))
        m["acc4"] = round(float((pred_va == y4_va).mean()), 4)
        log.info("epoch %d VAL binary acc %.4f f1 %.4f (4cls %.4f)",
                 epoch, m["acc"], m["f1"], m["acc4"])
        if m["f1"] > best["f1"]:
            best = dict(m, epoch=epoch)
            torch.save(model.state_dict(), ckpt_path)

    model.load_state_dict(torch.load(ckpt_path, weights_only=True))
    prob_va, ids_va = predict(model, dl_va, device)
    common.save_predictions(name, "val", ids_va, prob_va.argmax(1), prob_va)
    prob_te, ids_te = predict(model, dl_te, device)
    common.save_predictions(name, "test", ids_te, prob_te.argmax(1), prob_te)

    best["train_minutes"] = round((time.time() - t0) / 60, 1)
    common.record_result(name, "finetune",
                         {"model": args.model, "epochs": args.epochs,
                          "batch": args.batch, "lr": args.lr, "device": device},
                         best, notes=f"best epoch {best['epoch']}, "
                                     f"{best['train_minutes']} min on {device}")
    log.info("done: best val f1 %.4f (epoch %d), %.1f min",
             best["f1"], best["epoch"], best["train_minutes"])


if __name__ == "__main__":
    main()
