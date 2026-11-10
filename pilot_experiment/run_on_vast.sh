#!/usr/bin/env bash
# For a vast.ai instance started from a PyTorch (CUDA) template: no Docker needed.
#   git clone <repo-url> && cd <repo> && bash run_on_vast.sh
set -euo pipefail
pip install -q "transformers==5.22.1" "accelerate==1.15.0"   # torch comes with the template
nvidia-smi --query-gpu=name,memory.total --format=csv
python3 baseline_judge.py run --model openbmb/MiniCPM5-2B --device cuda --results out/baseline_results.jsonl
python3 baseline_judge.py summarize --results out/baseline_results.jsonl
