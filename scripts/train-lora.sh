#!/bin/bash
# Quick LoRA training launcher
# Usage: train-lora.sh [sdxl|flux] <trigger_word> <dataset_dir>
#
# PREPARATION:
# 1. Create a folder with 15-20 high-quality photos of your subject
# 2. All photos should be well-lit, varied poses/angles, tight crops
# 3. Name the folder with repeats: e.g., "20_ohwx" (20 repeats, trigger word "ohwx")
# 4. Place that folder under /data/training/current_dataset/

set -e
MODEL_TYPE="${1:-sdxl}"
TRIGGER="${2:-ohwx}"
DATASET="${3:-/data/training/current_dataset}"

cd ~/dev/sd-scripts
source .venv/bin/activate

# Stop ComfyUI to free GPU memory
echo "Stopping ComfyUI for training..."
sudo systemctl stop comfyui 2>/dev/null || true
sleep 2

if [ "$MODEL_TYPE" == "flux" ]; then
    echo "Training FLUX LoRA with trigger word: $TRIGGER"
    echo "Dataset: $DATASET"
    accelerate launch --mixed_precision bf16 flux_train_network.py \
        --config_file training_configs/train_flux_lora.toml \
        --train_data_dir "$DATASET"
elif [ "$MODEL_TYPE" == "sdxl" ]; then
    echo "Training SDXL LoRA with trigger word: $TRIGGER"
    echo "Dataset: $DATASET"
    accelerate launch --mixed_precision bf16 sdxl_train_network.py \
        --config_file training_configs/train_sdxl_lora.toml \
        --train_data_dir "$DATASET"
else
    echo "Usage: train-lora.sh [sdxl|flux] <trigger_word> <dataset_dir>"
    exit 1
fi

echo "Training complete! LoRA saved to /data/training/output/"
echo "Copy to /mnt/vault/models/comfyui/loras/ to use in ComfyUI"

# Restart ComfyUI
echo "Restarting ComfyUI..."
sudo systemctl start comfyui
