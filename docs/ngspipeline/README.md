# ngspipeline → ALIVE plumbing check (2026-09-17)

Upstream: [jam-sudo/ngspipeline](https://github.com/jam-sudo/ngspipeline) (dev `21204d9`) produced `alive/pooled.h5ad` from the raw FASTQ of Replogle 2022 K562 essential GEM groups 1–12 (SRA PRJNA831566) on the Northeastern Discovery cluster: 104,551 single-assignment cells × 85,308 genes, 2,052 perturbation labels, 3,780 `non-targeting` cells, sha256 `ce24bff91fca6907bb4c2c1955fb436e081bcb2511516ea683c81f5f584f2da2`.

This directory records that ALIVE's CLI consumed that file **with zero changes to `src/alive`**:

```
alive cartographer prepare --config configs/cartographer_trust_gate_ngspipeline_pool12_plumbing.yaml \
    --data-card docs/ngspipeline/data_card_ngspipeline_pool12.json --mock-encoder      # run 199f4bc77d2907b4, 11 s
alive cartographer fit --run-id 199f4bc77d2907b4                                        # 86 s
```

| item | value |
| --- | --- |
| eligible perturbations (usable sequence AND ≥ 64 cells) | 437 (excluded 1,614: 1,596 below `min_cells`, 18 without a usable UniProt sequence) |
| splits (seed 20260621) | base_train 197 · method_development 109 · conformal_calibration 66 · sealed_evaluation 65 |
| fit | 24,021 cells, 2,000 HVGs, PCA 50, additive ridge α = 100 (3-fold CV) |
| sequences | UniProtKB 2026_03, reviewed human, exactly-one rule: 1,993 usable of 2,062 library genes |

`--mock-encoder` and the plumbing config mean **no scientific claim**: this is the same end-to-end check the `k562_mini` config exists for. A scientific run on this data would go through the owner-approved A100 runbook with the real ESM-2 encoder. Neither the sealed evaluation nor any sealed store was touched. Data files are not committed (`data/ngspipeline/` is local); the run summary and ledger are in this directory.
