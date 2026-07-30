#!/usr/bin/env bash
set -euo pipefail

ROOT=${DIFFUERASER_ROOT:?Set DIFFUERASER_ROOT to the DiffuEraser checkout}
HF=${HF_BIN:-hf}
PROPAINTER_WEIGHTS=${PROPAINTER_WEIGHTS:-}

mkdir -p "${ROOT}/weights"

"${HF}" download lixiaowen/diffuEraser \
  --revision ad510dca07fa8e155d4bd8d002085bb8ec8f60e5 \
  --include 'brushnet/*.json' 'brushnet/*.safetensors' \
            'unet_main/*.json' 'unet_main/*.safetensors' \
  --local-dir "${ROOT}/weights/diffuEraser"

"${HF}" download stable-diffusion-v1-5/stable-diffusion-v1-5 \
  --revision 451f4fe16113bff5a5d2269ed5ad43b0592e9a14 \
  --include 'feature_extractor/*' 'model_index.json' \
            'safety_checker/config.json' \
            'safety_checker/model.safetensors' \
            'scheduler/*' 'text_encoder/config.json' \
            'text_encoder/model.safetensors' 'tokenizer/*' \
  --local-dir "${ROOT}/weights/stable-diffusion-v1-5"

"${HF}" download stabilityai/sd-vae-ft-mse \
  --revision 31f26fdeee1355a5c34592e401dd41e45d25a493 \
  --include 'config.json' 'diffusion_pytorch_model.safetensors' \
  --local-dir "${ROOT}/weights/sd-vae-ft-mse"

"${HF}" download wangfuyun/PCM_Weights \
  --revision 39560fead4ce00f94db3cb8e93dd8fba90ec0be6 \
  --include 'sd15/pcm_sd15_smallcfg_2step_converted.safetensors' \
  --local-dir "${ROOT}/weights/PCM_Weights"

mkdir -p "${ROOT}/weights/propainter"
if [[ -n "${PROPAINTER_WEIGHTS}" ]]; then
  for name in ProPainter.pth recurrent_flow_completion.pth raft-things.pth; do
    source_path="${PROPAINTER_WEIGHTS}/${name}"
    destination="${ROOT}/weights/propainter/${name}"
    if [[ ! -e "${source_path}" ]]; then
      echo "Missing ProPainter weight: ${source_path}" >&2
      exit 1
    fi
    if [[ ! -e "${destination}" ]]; then
      ln -s "${source_path}" "${destination}"
    fi
  done
else
  echo "PROPAINTER_WEIGHTS is unset; skipping optional ProPainter symlinks."
fi

find "${ROOT}/weights" -type f -printf '%p %s\n' | sort
echo DIFFUERASER_WEIGHTS_READY
