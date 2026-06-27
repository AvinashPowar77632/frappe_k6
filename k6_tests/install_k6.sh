#!/usr/bin/env bash
# ============================================================
# install_k6.sh — Install Grafana k6 on Ubuntu/Debian
# ============================================================
set -e

echo "======================================================"
echo "  Installing Grafana k6 Load Testing Tool"
echo "======================================================"

OS=$(uname -s)
ARCH=$(uname -m)

if [[ "$OS" == "Linux" ]]; then
    if command -v apt-get &>/dev/null; then
        echo "[INFO] Detected Debian/Ubuntu — using official Grafana APT repo..."
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://dl.k6.io/key.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/k6-archive-keyring.gpg
        echo "deb [signed-by=/etc/apt/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
            | sudo tee /etc/apt/sources.list.d/k6.list
        sudo apt-get update -qq
        sudo apt-get install -y k6
    elif command -v yum &>/dev/null; then
        echo "[INFO] Detected RHEL/CentOS — using official Grafana RPM repo..."
        sudo dnf install -y https://dl.k6.io/rpm/repo.rpm
        sudo dnf install -y k6
    else
        echo "[ERROR] Unsupported Linux distro. Install manually from https://k6.io/docs/get-started/installation/"
        exit 1
    fi
elif [[ "$OS" == "Darwin" ]]; then
    echo "[INFO] Detected macOS — using Homebrew..."
    brew install k6
else
    echo "[ERROR] Unsupported OS: $OS"
    exit 1
fi

echo ""
echo "======================================================"
k6 version
echo "======================================================"
echo "✅ k6 installed successfully!"
echo ""
echo "Next step — generate site config:"
echo "  cd $(dirname "$0")"
echo "  python3 setup_config.py --site <your-site> --bench <bench-path>"
echo ""
echo "Then run tests:"
echo "  ./run_tests.sh --site <your-site> --scenario smoke"
echo "======================================================"
