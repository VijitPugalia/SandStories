#!/usr/bin/env bash
# SAM2 pass 2: "arm."-only tracking with phantom-box filter, per segment.
# Usage: run_sam2_arm_pass.sh <session_work_dir> <gpu_id>
set -euo pipefail
WORK="$(cd "$1" && pwd)"
GPU="${2:-0}"
SAM2_PY="${SAM2_PY:?set SAM2_PY to the Grounded-SAM-2 Python executable}"
SAM2_REPO="${SAM2_ROOT:?set SAM2_ROOT to the Grounded-SAM-2 checkout}"
TRACKER_SCRIPT="${TRACKER_SCRIPT:-$(cd "$(dirname "$0")" && pwd)/grounded_sam2_tracking_sandiv.py}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
ulimit -n 8192

test -f "$TRACKER_SCRIPT"

for SEGDIR in "$WORK"/sam2_seg_*; do
  SEGN=$(basename "$SEGDIR")
  OUTDIR="$WORK/sam2_output_arm_$SEGN"
  N=$(ls "$SEGDIR" | wc -l)
  DONE=$(ls "$OUTDIR/binary_masks" 2>/dev/null | wc -l || true)
  if [ "$DONE" -ge "$N" ]; then
    echo "skip $SEGN ($DONE/$N done)"
    continue
  fi
  rm -rf "$OUTDIR"
  echo "=== arm pass $SEGN gpu=$GPU ==="
  (cd "$SAM2_REPO" && CUDA_VISIBLE_DEVICES="$GPU" "$SAM2_PY" "$TRACKER_SCRIPT" \
    --video-dir "$SEGDIR" --output-dir "$OUTDIR" \
    --text "arm." --step 10 --box-threshold 0.35 --text-threshold 0.20 \
    --max-box-area-ratio 0.5 \
    --sam2-checkpoint checkpoints/sam2.1_hiera_large.pt \
    --sam2-config configs/sam2.1/sam2.1_hiera_l.yaml \
    --grounding-model IDEA-Research/grounding-dino-tiny 2>&1 | tail -3)
  echo "done $SEGN: $(ls "$OUTDIR/binary_masks" | wc -l) masks"
done

rm -rf "$WORK/sam2_output_arm/binary_masks"
mkdir -p "$WORK/sam2_output_arm/binary_masks"
for SEGDIR in "$WORK"/sam2_seg_*; do
  SEGN=$(basename "$SEGDIR")
  cp "$WORK/sam2_output_arm_$SEGN"/binary_masks/*.png "$WORK"/sam2_output_arm/binary_masks/ 2>/dev/null || true
done
echo "ALL DONE: total arm masks = $(ls "$WORK/sam2_output_arm/binary_masks" | wc -l)"
