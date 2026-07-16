# Experiment log (validation split — binary accept/reject)

| experiment | kind | val metrics | notes |
|---|---|---|---|
| heuristics_gbt | heuristic | acc=0.7749 f1=0.8349 p=0.7657 r=0.9178 | 4cls-val-acc 0.7728 |
| probe_siglip2_logreg | probe | acc=0.828 f1=0.8492 p=0.9306 r=0.7808 | 4cls-val-acc 0.7771 |
| probe_siglip2_mlp | probe | acc=0.8577 f1=0.8866 p=0.8763 r=0.8973 | 4cls-val-acc 0.8174 |
| zeroshot_siglip2 | zero-shot | acc=0.7431 f1=0.7843 p=0.8178 r=0.7534 | 4cls-val-acc 0.6433 |
| finetune_efficientnet_b0 | finetune | acc=0.7389 f1=0.7784 p=0.8213 r=0.7397 | best epoch 3, 14.1 min on mps |
