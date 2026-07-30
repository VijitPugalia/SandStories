#!/usr/bin/env bash
set -euo pipefail

workspace=${CASPER_WORKSPACE:?Set CASPER_WORKSPACE to the Generative Omnimatte checkout}
venv=${CASPER_VENV:?Set CASPER_VENV to the Python virtual environment}
config=${CASPER_CONFIG:-config/sandiv_casper_cog5b_3gpu.py}
gpu_count=${CASPER_GPU_COUNT:-3}

cd "$workspace"
export PATH="$venv/bin:$PATH"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2}"
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

exec "$venv/bin/torchrun" \
  --standalone \
  --nproc_per_node="$gpu_count" \
  inference/cogvideox_fun/predict_v2v.py \
  --config="$config"
