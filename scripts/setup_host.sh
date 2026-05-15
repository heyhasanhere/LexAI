#!/usr/bin/env bash
# Host prerequisites for LexAI.
# Run once on any server before starting docker compose.
# Requires: Ubuntu 22.04+, NVIDIA drivers already installed.
set -euo pipefail

# --- Docker ---
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in for group changes to take effect."
else
    echo "Docker already installed: $(docker --version)"
fi

# --- NVIDIA Container Toolkit ---
if ! dpkg -s nvidia-container-toolkit &>/dev/null; then
    echo "Installing NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

    sudo apt-get update -qq
    sudo apt-get install -y nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    echo "NVIDIA Container Toolkit installed."
else
    echo "NVIDIA Container Toolkit already installed."
fi

# --- System dependencies ---
echo "Installing system packages..."
sudo apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    libpq-dev \
    python3-pip

# --- Python dependencies ---
echo "Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "Setup complete. Run 'docker compose up -d' to start backing services."
echo "Then: uvicorn src.api.routes:app --host 0.0.0.0 --port 8000"
