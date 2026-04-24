#!/usr/bin/env bash
# ============================================
# setup_wasmixer_env.sh
# Full environment setup for WASMixer + metrics
# Target: Grid5000 (Ubuntu/Debian)
# ============================================

set -e

echo "============================================"
echo " WASMixer + WASM Metrics Environment Setup"
echo "============================================"

# -------- CONFIG --------
PYTHON_BIN=python3
VENV_DIR=.venv
PROJECT_ROOT=$(pwd)

# -------- System packages --------
echo "[1/8] Installing system packages..."
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  nodejs npm \
  clang lld build-essential \
  git cmake wget curl unzip \
  wabt binaryen

# -------- 2. Check WABT --------
echo "[2/8] Checking WABT..."
wasm2wat --version
wasm-validate --version

# -------- check Binaryen --------
echo "[3/8] Checking Binaryen..."
wasm-dis --version
wasm-opt --version

# -------- Install Wasmtime --------
echo "[4/8] Installing Wasmtime..."
if ! command -v wasmtime &> /dev/null; then
  curl https://wasmtime.dev/install.sh -sSf | bash
fi

export PATH="$HOME/.wasmtime/bin:$PATH"
wasmtime --version

# -------- (Optional) Emscripten --------
echo "[5/8] Installing Emscripten (for .c → wasm)..."
if [ ! -d "$HOME/emsdk" ]; then
  git clone https://github.com/emscripten-core/emsdk.git "$HOME/emsdk"
fi

cd "$HOME/emsdk"
./emsdk install latest
./emsdk activate latest
source ./emsdk_env.sh
cd "$PROJECT_ROOT"

emcc --version || echo "⚠ emcc not found in current shell (re-source emsdk_env.sh)"

# -------- Python virtual environment --------
echo "[6/8] Setting up Python virtual environment..."
$PYTHON_BIN -m venv $VENV_DIR
source $VENV_DIR/bin/activate
pip install --upgrade pip

# -------- Python requirements --------
echo "[7/8] Installing Python requirements..."
cat <<EOF > requirements.txt
rapidfuzz>=3.5.0
EOF

pip install -r requirements.txt

# --------  Node dependencies --------
echo "[8/8] Installing Node.js dependencies..."
if [ ! -f package.json ]; then
  npm init -y
fi

npm install puppeteer minimist @wasmer/wasi @wasmer/wasmfs

# -------- Final checks --------
echo "============================================"
echo " Environment verification"
echo "============================================"

echo "[✔] Python:" $(python --version)
echo "[✔] Node:" $(node --version)
echo "[✔] npm:" $(npm --version)
echo "[✔] wasm2wat:" $(which wasm2wat)
echo "[✔] wasm-dis:" $(which wasm-dis)
echo "[✔] wasm-opt:" $(which wasm-opt)
echo "[✔] wasmtime:" $(which wasmtime)
echo "[✔] emcc:" $(which emcc || echo "not in PATH")

echo
echo " Setup complete."
echo "➡ Activate env with: source .venv/bin/activate"
echo "➡ If using emcc, run: source ~/emsdk/emsdk_env.sh"
echo "============================================"
