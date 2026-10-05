#!/usr/bin/env bash
# Produce every Phase 5-6 result from the baseline batch, in order; stops on the first error.
#   bash evaluation/scripts/make_results.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
M=evaluation/data/manifest.csv
echo "runs in manifest: $(($(wc -l < $M) - 1)); not ok: $(awk -F, 'NR>1 && $12!="ok"' $M | wc -l)"
python3 evaluation/scripts/extract_metrics.py --manifest $M --out evaluation/data/metrics.csv
python3 evaluation/scripts/summarise.py --metrics evaluation/data/metrics.csv --outdir evaluation/results
python3 evaluation/scripts/sensitivity_offline.py --manifest $M --outdir evaluation/results/sensitivity
python3 evaluation/scripts/make_figures.py --metrics evaluation/data/metrics.csv \
    --sensitivity evaluation/results/sensitivity --out evaluation/results/figures
echo "results: evaluation/results/tables.md, sensitivity/sensitivity.md, figures/"
