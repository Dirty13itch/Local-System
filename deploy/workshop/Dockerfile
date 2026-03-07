FROM nvcr.io/nvidia/pytorch:25.02-py3

ENV DEBIAN_FRONTEND=noninteractive
ENV COMFYUI_DIR=/opt/ComfyUI

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Clone ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI.git ${COMFYUI_DIR}

WORKDIR ${COMFYUI_DIR}

# Install torchaudio (needed by WanVideoWrapper). This upgrades torch from NGC 2.7.0a0
# to stable 2.10.0+cu128 which has native Blackwell sm_120 support — verified working.
# Remove NGC's stale opencv (compiled for numpy 1.x) and its artifacts to avoid conflicts.
RUN pip uninstall -y opencv 2>/dev/null; \
    rm -rf /usr/local/lib/python3.12/dist-packages/cv2* && \
    pip install --no-cache-dir torchaudio opencv-python-headless

# Install ComfyUI requirements, filtering out torch ecosystem (already installed above)
RUN grep -viE "^torch(vision|audio)?([=>< ]|$)" requirements.txt > requirements_filtered.txt && \
    pip install --no-cache-dir -r requirements_filtered.txt

# Install gitpython for ComfyUI-Manager
RUN pip install --no-cache-dir gitpython

# ─── Face-ID Pipeline Dependencies ──────────────────────────────────────────
# These are required by PuLID-Flux, ReActor, and IPAdapter custom nodes.
# Custom nodes are mounted as Docker volumes and persist across rebuilds,
# but their Python dependencies must be baked into the image.
RUN pip install --no-cache-dir \
    insightface \
    onnxruntime-gpu \
    facexlib \
    timm \
    segment_anything \
    toml

# Ensure numpy stays at 2.x (facexlib tries to pull 1.x)
RUN pip install --no-cache-dir "numpy>=2.0"

# Install ComfyUI Manager
RUN git clone https://github.com/ltdrdata/ComfyUI-Manager.git ${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager

# Install custom nodes for video generation (Wan2.x)
RUN git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git ${COMFYUI_DIR}/custom_nodes/ComfyUI-WanVideoWrapper && \
    pip install --no-cache-dir -r ${COMFYUI_DIR}/custom_nodes/ComfyUI-WanVideoWrapper/requirements.txt

RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git ${COMFYUI_DIR}/custom_nodes/ComfyUI-KJNodes && \
    pip install --no-cache-dir -r ${COMFYUI_DIR}/custom_nodes/ComfyUI-KJNodes/requirements.txt

EXPOSE 8188

# ─── Entrypoint Script ──────────────────────────────────────────────────────
# Creates symlinks from local model dirs to NFS-mounted models at runtime.
# PuLID hardcodes folder_paths.models_dir for InsightFace, so we symlink
# /opt/ComfyUI/models/insightface → /mnt/vault/models/comfyui/insightface
# to ensure model files are found regardless of how PuLID resolves paths.
RUN printf '#!/bin/bash\n\
# Symlink model directories from NFS mount (if available)\n\
if [ -d /mnt/vault/models/comfyui/insightface ]; then\n\
    rm -rf /opt/ComfyUI/models/insightface\n\
    ln -sf /mnt/vault/models/comfyui/insightface /opt/ComfyUI/models/insightface\n\
    echo "Linked insightface models from NFS"\n\
fi\n\
exec python3 main.py "$@"\n' > /opt/ComfyUI/entrypoint.sh && chmod +x /opt/ComfyUI/entrypoint.sh

ENTRYPOINT ["/opt/ComfyUI/entrypoint.sh"]
CMD ["--listen", "0.0.0.0", "--port", "8188"]
