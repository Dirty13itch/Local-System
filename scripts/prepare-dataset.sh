#!/bin/bash
# Usage: prepare-dataset.sh <photo_dir> <trigger_word> [sdxl|flux]
# Example: prepare-dataset.sh ~/photos/jane janedoe sdxl

set -e

PHOTO_DIR="${1:?Usage: prepare-dataset.sh <photo_dir> <trigger_word> [sdxl|flux]}"
TRIGGER="${2:?Missing trigger word}"
MODEL_TYPE="${3:-sdxl}"

if [ "$MODEL_TYPE" = "flux" ]; then
    RESOLUTION=512
else
    RESOLUTION=1024
fi

echo "=== Dataset Preparation ==="
echo "Photos:     $PHOTO_DIR"
echo "Trigger:    $TRIGGER"
echo "Model:      $MODEL_TYPE"
echo "Resolution: ${RESOLUTION}x${RESOLUTION}"
echo ""

python3 ~/dev/prepare_dataset.py "$PHOTO_DIR" "$TRIGGER" --resolution "$RESOLUTION"
echo ""
echo "=== Done ==="
echo "Next: Train with kohya-ss or ComfyUI Realtime-Lora"
