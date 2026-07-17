#!/usr/bin/env python3
"""Generate publication figures from the result JSONs.

Writes PNG (300 dpi, for LaTeX) + SVG (for the web) to ml/figures/.
Also emits figures/data.json — the same numbers the web page reads, so the
paper and the interactive site are guaranteed to show identical values.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ML = Path(__file__).resolve().parent
FIG = ML / "figures"
FIG.mkdir(exist_ok=True)

# ---- palette ----
INK = "#1a1a2e"
WIN = "#2a9d8f"      # winner / good
TEACH = "#e76f51"    # LLM teacher
NEG = "#c1121f"      # negative result
MID = "#6c757d"      # neutral
ZERO = "#457b9d"     # zero-shot
plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 11, "axes.edgecolor": "#cccccc",
    "axes.linewidth": 0.8, "axes.grid": True, "grid.color": "#eeeeee",
    "grid.linewidth": 0.8, "figure.dpi": 120, "savefig.bbox": "tight",
})


def save(fig, name):
    fig.savefig(FIG / f"{name}.png", dpi=300)
    fig.savefig(FIG / f"{name}.svg")
    plt.close(fig)
    print("wrote", name)


# ---- shared data (mirrors results/, single source of truth) ----
GOLD = [   # (label, gold_acc, ci_lo, ci_hi, color, kind)
    ("SigLIP2 + logreg", 0.860, 0.815, 0.905, WIN, "winner"),
    ("Zero-shot SigLIP2", 0.835, 0.785, 0.885, ZERO, "zeroshot"),
    ("SigLIP2 + MLP", 0.780, 0.725, 0.835, MID, "probe"),
    ("DINOv2 + MLP", 0.765, 0.710, 0.825, MID, "probe"),
    ("LLM teacher (mimo-v2.5)", 0.755, 0.700, 0.815, TEACH, "teacher"),
    ("MobileCLIP-S0 + MLP", 0.750, 0.695, 0.810, MID, "probe"),
    ("DINOv3 + MLP", 0.735, 0.675, 0.795, MID, "probe"),
    ("EfficientNet-B0 fine-tune", 0.715, 0.650, 0.775, NEG, "negative"),
    ("Heuristics (GBT)", 0.625, 0.555, 0.695, NEG, "negative"),
]
SILVER_GOLD = [  # (label, silver_val_acc, gold_acc, color)
    ("SigLIP2+logreg", 0.828, 0.860, WIN),
    ("SigLIP2+MLP", 0.858, 0.780, NEG),
    ("DINOv3+MLP", 0.820, 0.735, NEG),
    ("MobileCLIP+MLP", 0.811, 0.750, MID),
    ("DINOv2+MLP", 0.794, 0.765, MID),
    ("Zero-shot", 0.743, 0.835, ZERO),
    ("EfficientNet FT", 0.732, 0.715, MID),
    ("Heuristics", 0.775, 0.625, NEG),
]
SPEED = [  # (label, mps_ms, cpu_ms, gold_acc, color)
    ("SigLIP2+logreg", 51.8, 124.9, 0.860, WIN),
    ("MobileCLIP-S0", 20.0, 167.9, 0.750, MID),
    ("EfficientNet-B0", 27.8, 528.5, 0.715, MID),
    ("Heuristics", 5.3, 5.3, 0.625, MID),
    ("LLM gate", 10000, 10000, 0.755, TEACH),
]
FUNNEL = [("arXiv papers", 1183), ("pages judged", 12266),
          ("diagram pages", 2552), ("figure crops", 5885),
          ("accepted diagrams", 2000)]
ABLATION = {"Full (dirty)": (0.860, 0.780), "Conservative −4%": (0.850, 0.810),
            "Aggressive −22%": (0.830, 0.845)}
CONF = np.array([[80, 8, 1, 2], [12, 74, 1, 3], [4, 1, 12, 1], [3, 4, 0, 24]])


def fig_leaderboard():
    fig, ax = plt.subplots(figsize=(8, 4.6))
    ys = np.arange(len(GOLD))[::-1]
    for y, (label, acc, lo, hi, color, kind) in zip(ys, GOLD):
        ax.barh(y, acc, color=color, height=0.62,
                edgecolor=INK if kind == "winner" else "none",
                linewidth=1.5, zorder=3)
        ax.plot([lo, hi], [y, y], color=INK, lw=1.4, zorder=4)
        ax.plot([lo, lo, ], [y, y], "|", color=INK, zorder=4)
        ax.text(acc + 0.006, y, f"{acc:.3f}", va="center", fontsize=9.5,
                fontweight="bold" if kind in ("winner", "teacher") else "normal")
    ax.axvline(0.755, color=TEACH, ls="--", lw=1.2, zorder=2)
    ax.text(0.755, len(GOLD) - 0.3, " LLM teacher", color=TEACH, fontsize=9)
    ax.set_yticks(ys)
    ax.set_yticklabels([g[0] for g in GOLD], fontsize=9.5)
    ax.set_xlim(0.55, 0.93)
    ax.set_xlabel("Accuracy on hand-verified gold set (n=200), 95% CI")
    ax.set_title("Crop gate: frozen SigLIP2 + logistic regression beats the LLM\n"
                 "teacher by 10.5 points (McNemar p = 0.0005)", fontsize=12,
                 fontweight="bold", loc="left")
    ax.grid(axis="y", visible=False)
    save(fig, "fig1_gold_leaderboard")


def fig_silver_gold():
    fig, ax = plt.subplots(figsize=(7.2, 5))
    for label, sv, gd, color in SILVER_GOLD:
        ax.plot([0, 1], [sv, gd], "-o", color=color, lw=2, markersize=6, zorder=3)
        ax.text(-0.03, sv, label, ha="right", va="center", fontsize=8.5, color=color)
        ax.text(1.03, gd, f"{gd:.2f}", ha="left", va="center", fontsize=8.5,
                color=color, fontweight="bold")
    ax.axhline(0.755, color=TEACH, ls="--", lw=1, zorder=1)
    ax.text(0.5, 0.758, "LLM teacher on gold", color=TEACH, fontsize=8.5, ha="center")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Silver validation\n(LLM labels)", "Gold test\n(hand-verified truth)"])
    ax.set_xlim(-0.35, 1.28)
    ax.set_ylabel("Binary accuracy")
    ax.set_title("The trap: models that top silver-validation collapse on gold\n"
                 "(they memorized the teacher's ~25% label noise)", fontsize=11.5,
                 fontweight="bold", loc="left")
    ax.grid(axis="x", visible=False)
    save(fig, "fig2_silver_vs_gold")


def fig_speed_accuracy():
    fig, ax = plt.subplots(figsize=(7.6, 5))
    for label, mps, cpu, acc, color in SPEED:
        ax.scatter(mps, acc, s=150, color=color, edgecolor=INK, linewidth=1,
                   zorder=3)
        dx = 1.12 if label != "LLM gate" else 0.62
        ax.annotate(label, (mps, acc), (mps * dx, acc + 0.004), fontsize=9,
                    color=color, fontweight="bold")
    ax.axhline(0.755, color=TEACH, ls="--", lw=1)
    ax.set_xscale("log")
    ax.set_xlim(3, 30000)
    ax.set_ylim(0.60, 0.90)
    ax.set_xlabel("Latency per decision (ms, log scale) — GPU/MPS")
    ax.set_ylabel("Gold accuracy")
    ax.set_title("Accuracy vs speed: the winner is ~200× faster than the LLM\n"
                 "at higher accuracy, on a laptop", fontsize=11.5,
                 fontweight="bold", loc="left")
    ax.annotate("", xy=(60, 0.86), xytext=(9000, 0.755),
                arrowprops=dict(arrowstyle="->", color=MID, lw=1, ls=":"))
    save(fig, "fig3_speed_accuracy")


def fig_funnel():
    """Honest left-to-right pipeline flow (not a funnel — the flow expands then
    contracts, so equal boxes + arrows read far more clearly than widths)."""
    from matplotlib.patches import FancyBboxPatch
    stages = [("arXiv\npapers", 1183, "#264653"),
              ("pages\njudged", 12266, "#2a6f77"),
              ("diagram\npages", 2552, "#2a9d8f"),
              ("figure\ncrops", 5885, "#8ab17d"),
              ("accepted\ndiagrams", 2000, "#e9c46a")]
    steps = ["render", "LLM gate\n21%+", "OCR", "gate 34%"]
    fig, ax = plt.subplots(figsize=(10.0, 3.2))
    n = len(stages)
    bw, bh, gap = 1.5, 1.5, 1.35
    for i, (label, v, c) in enumerate(stages):
        x = i * (bw + gap)
        box = FancyBboxPatch((x, 0), bw, bh,
                             boxstyle="round,pad=0.02,rounding_size=0.12",
                             linewidth=0, facecolor=c, zorder=3)
        ax.add_patch(box)
        dark = i in (0, 1, 2)
        ax.text(x + bw / 2, 0.92, f"{v:,}", ha="center", va="center",
                color="white" if dark else INK, fontweight="bold", fontsize=15,
                zorder=4)
        ax.text(x + bw / 2, 0.42, label, ha="center", va="center",
                color="white" if dark else INK, fontsize=9.5, zorder=4)
        if i < n - 1:
            ax.annotate("", xy=(x + bw + gap - 0.05, bh / 2), xytext=(x + bw + 0.05, bh / 2),
                        arrowprops=dict(arrowstyle="-|>", color=MID, lw=1.6))
            ax.text(x + bw + gap / 2, bh / 2 + 0.42, steps[i], ha="center",
                    va="bottom", fontsize=7.4, color=MID, style="italic")
    ax.set_xlim(-0.3, n * (bw + gap) - gap + 0.3)
    ax.set_ylim(-0.3, bh + 0.9)
    ax.axis("off")
    ax.set_title("Data provenance: how 1,183 arXiv papers became 2,000 labeled diagrams\n"
                 "(pipeline cost $20.36, fully resumable)", fontsize=11.5,
                 fontweight="bold", loc="left")
    save(fig, "fig4_data_funnel")


def fig_ablation():
    fig, ax = plt.subplots(figsize=(6.8, 4.4))
    x = np.arange(len(ABLATION))
    lr = [v[0] for v in ABLATION.values()]
    ml = [v[1] for v in ABLATION.values()]
    ax.bar(x - 0.19, lr, 0.36, label="Logistic regression (winner)", color=WIN, zorder=3)
    ax.bar(x + 0.19, ml, 0.36, label="MLP (overfitter)", color=MID, zorder=3)
    ax.axhline(0.755, color=TEACH, ls="--", lw=1)
    ax.text(2.4, 0.758, "teacher", color=TEACH, fontsize=8.5)
    for xi, v in zip(x - 0.19, lr):
        ax.text(xi, v + 0.004, f"{v:.2f}", ha="center", fontsize=8.5)
    for xi, v in zip(x + 0.19, ml):
        ax.text(xi, v + 0.004, f"{v:.2f}", ha="center", fontsize=8.5)
    ax.set_xticks(x)
    ax.set_xticklabels(list(ABLATION.keys()))
    ax.set_ylim(0.68, 0.90)
    ax.set_ylabel("Gold accuracy")
    ax.set_xlabel("Training-set label cleaning (confident learning)")
    ax.set_title("Cleaning label noise doesn't help the winner\n"
                 "(it removes data, not the noise it already ignores)",
                 fontsize=11.5, fontweight="bold", loc="left")
    ax.legend(fontsize=9, loc="lower left")
    ax.grid(axis="x", visible=False)
    save(fig, "fig5_ablation")


def fig_confusion():
    fig, ax = plt.subplots(figsize=(5.6, 5))
    classes = ["diagram", "data_plot", "photo", "fragment"]
    im = ax.imshow(CONF, cmap="BuGn")
    for i in range(4):
        for j in range(4):
            ax.text(j, i, CONF[i, j], ha="center", va="center",
                    color="white" if CONF[i, j] > 40 else INK, fontweight="bold")
    ax.set_xticks(range(4)); ax.set_yticks(range(4))
    ax.set_xticklabels(classes, rotation=30, ha="right")
    ax.set_yticklabels(classes)
    ax.set_xlabel("Predicted"); ax.set_ylabel("Gold truth")
    ax.set_title("Winner's 4-class confusion on gold\n(errors concentrate on the "
                 "diagram/data_plot boundary)", fontsize=11, fontweight="bold", loc="left")
    ax.grid(False)
    save(fig, "fig6_confusion")


def main():
    fig_leaderboard()
    fig_silver_gold()
    fig_speed_accuracy()
    fig_funnel()
    fig_ablation()
    fig_confusion()
    data = {"gold": [{"model": g[0], "acc": g[1], "ci": [g[2], g[3]], "kind": g[5]}
                     for g in GOLD],
            "silver_gold": [{"model": s[0], "silver": s[1], "gold": s[2]}
                            for s in SILVER_GOLD],
            "speed": [{"model": s[0], "mps_ms": s[1], "cpu_ms": s[2], "acc": s[3]}
                      for s in SPEED],
            "funnel": [{"stage": f[0], "n": f[1]} for f in FUNNEL],
            "ablation": {k: {"logreg": v[0], "mlp": v[1]} for k, v in ABLATION.items()},
            "headline": {"winner_acc": 0.860, "teacher_acc": 0.755,
                         "mcnemar_p": 0.0005, "winner_ms_mps": 51.8,
                         "llm_ms": "4000-17000", "gold_n": 200,
                         "dataset_n": 2000, "papers": 1183, "cost_usd": 20.36}}
    (FIG / "data.json").write_text(json.dumps(data, indent=2))
    print("wrote data.json")


if __name__ == "__main__":
    main()
