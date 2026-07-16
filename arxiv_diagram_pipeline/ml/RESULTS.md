# Experiment log (validation split — binary accept/reject)

| experiment | kind | val metrics | notes |
|---|---|---|---|
| heuristics_gbt | heuristic | acc=0.7749 f1=0.8349 p=0.7657 r=0.9178 | 4cls-val-acc 0.7728 |
| probe_siglip2_logreg | probe | acc=0.828 f1=0.8492 p=0.9306 r=0.7808 | 4cls-val-acc 0.7771 |
| probe_siglip2_mlp | probe | acc=0.8577 f1=0.8866 p=0.8763 r=0.8973 | 4cls-val-acc 0.8174 |
| zeroshot_siglip2 | zero-shot | acc=0.7431 f1=0.7843 p=0.8178 r=0.7534 | 4cls-val-acc 0.6433 |
| finetune_efficientnet_b0 | finetune | acc=0.7389 f1=0.7784 p=0.8213 r=0.7397 | best epoch 3, 14.1 min on mps |
| probe_dinov2_logreg | probe | acc=0.7792 f1=0.8081 p=0.876 r=0.75 | 4cls-val-acc 0.7049 |
| probe_dinov2_mlp | probe | acc=0.7941 f1=0.8364 p=0.8239 r=0.8493 | 4cls-val-acc 0.7452 |
| probe_dinov3_logreg | probe | acc=0.7792 f1=0.8 p=0.9123 r=0.7123 | 4cls-val-acc 0.6985 |
| probe_dinov3_mlp | probe | acc=0.8195 f1=0.8653 p=0.8053 r=0.9349 | 4cls-val-acc 0.758 |
| probe_mobileclip_logreg | probe | acc=0.8174 f1=0.8442 p=0.8962 r=0.7979 | 4cls-val-acc 0.7558 |
| probe_mobileclip_mlp | probe | acc=0.811 f1=0.8514 p=0.8306 r=0.8733 | 4cls-val-acc 0.7622 |
| cascade_probe_siglip2_logreg | cascade | acc=0.7495 f1=None p=0.9579 r=None | lo=0.55 hi=0.55 coverage=100% |
| cascade_probe_siglip2_logreg | cascade | acc=0.8429 f1=None p=0.9129 r=None | lo=0.35 hi=0.35 coverage=100% |
