#!/bin/bash
# setup_node.sh
# Run this script on EACH Grid5000 node before launching the evaluation pipeline.
# Usage: bash setup_node.sh
# Compatible with Ubuntu 22.04, Node 12.22, no sudo restrictions.

set -e
echo "======================================================"
echo " Setup node: $(hostname)"
echo " Date: $(date)"
echo "======================================================"

# ---- Paths (adjust if needed) ----
STORAGE="/srv/storage/killerdroid@storage3.rennes.grid5000.fr/datasets/Andromatch_Paper/SOK_WebAsssembly_2025_Grid5000"
SCRIPTS_DIR="$STORAGE/Wasm/WASMixer-main"
BINARYEN_VERSION="116"
BINARYEN_DIR="/tmp/binaryen-version_${BINARYEN_VERSION}"
PUPPETEER_DIR="/tmp/puppeteer_env"

# ======================================================
# 1. Python dependencies
# ======================================================
echo ""
echo "[1/5] Installing Python dependencies..."

if python3 -c "import rapidfuzz, networkx, scipy, numpy" 2>/dev/null; then
    echo "  Python deps already installed -- skipping"
else
    # Try with venv first (preferred on Grid5000)
    if [ -f "$STORAGE/Wasm/venv/bin/activate" ]; then
        source "$STORAGE/Wasm/venv/bin/activate"
        pip install --quiet rapidfuzz networkx scipy numpy
    else
        # Try global install
        pip3 install --quiet rapidfuzz networkx scipy numpy 2>/dev/null || \
        pip install --quiet rapidfuzz networkx scipy numpy 2>/dev/null || \
        echo "  WARNING: pip install failed -- activate your venv manually"
    fi
fi

python3 -c "import rapidfuzz, networkx, scipy, numpy; print('  OK: rapidfuzz networkx scipy numpy')"

# ======================================================
# 2. WABT (system package -- should already be installed)
# ======================================================
echo ""
echo "[2/5] Checking WABT..."
if which wasm2wat > /dev/null 2>&1; then
    echo "  OK: $(wasm2wat --version 2>&1 | head -1)"
else
    echo "  Installing WABT..."
    apt-get install -y wabt 2>/dev/null || echo "  WARNING: apt-get failed -- install wabt manually"
fi

# ======================================================
# 3. Binaryen 116 (system version 105 is too old for --print-cfg)
# ======================================================
echo ""
echo "[3/5] Installing Binaryen version ${BINARYEN_VERSION}..."

if [ -f "$BINARYEN_DIR/bin/wasm-opt" ]; then
    echo "  Already installed at $BINARYEN_DIR"
else
    echo "  Downloading binaryen ${BINARYEN_VERSION}..."
    cd /tmp
    wget -q --show-progress \
        "https://github.com/WebAssembly/binaryen/releases/download/version_${BINARYEN_VERSION}/binaryen-version_${BINARYEN_VERSION}-x86_64-linux.tar.gz" \
        -O /tmp/binaryen.tar.gz
    tar xzf /tmp/binaryen.tar.gz -C /tmp/
    rm -f /tmp/binaryen.tar.gz
    echo "  Installed at $BINARYEN_DIR"
fi

export PATH="$BINARYEN_DIR/bin:$PATH"
echo "  wasm-opt version: $(wasm-opt --version 2>&1)"

# Persist PATH for this session
echo "export PATH=\"$BINARYEN_DIR/bin:\$PATH\"" >> ~/.bashrc_wasm_setup 2>/dev/null || true

# ======================================================
# 4. System libraries required by Chromium headless
# ======================================================
echo ""
echo "[4/5] Installing Chromium system libraries..."

apt-get install -y \
    libgbm1 \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libpango-1.0-0 \
    libcairo2 \
    libnss3 \
    libnspr4 \
    --fix-missing \
    -qq 2>/dev/null && echo "  OK: Chromium libs installed" || \
    echo "  WARNING: some libs may be missing (apt-get failed)"

# ======================================================
# 5. Puppeteer (Node 12 compatible version 14.4.1)
# ======================================================
echo ""
echo "[5/5] Installing Puppeteer..."

# Check if already installed and working
if NODE_PATH="$PUPPETEER_DIR/node_modules" \
   node -e "require('puppeteer'); process.exit(0)" 2>/dev/null; then
    echo "  Puppeteer already installed and working -- skipping"
else
    echo "  Installing puppeteer@14.4.1 in $PUPPETEER_DIR ..."

    mkdir -p "$PUPPETEER_DIR"

    # Write package.json
    cat > "$PUPPETEER_DIR/package.json" << 'PKGJSON'
{
  "name": "browser-runner",
  "version": "1.0.0",
  "description": "Puppeteer for Wasm behavioral analysis",
  "license": "MIT",
  "dependencies": {
    "puppeteer": "14.4.1"
  },
  "engines": {
    "node": ">=12.22.0"
  }
}
PKGJSON

    cd "$PUPPETEER_DIR"
    npm install --quiet 2>&1 | grep -v "^npm warn" | grep -v "^$" || true

    # Verify
    if NODE_PATH="$PUPPETEER_DIR/node_modules" \
       node -e "require('puppeteer'); process.exit(0)" 2>/dev/null; then
        echo "  OK: puppeteer installed"
    else
        echo "  ERROR: puppeteer install failed -- check node version:"
        node --version
    fi
fi

# ======================================================
# Final verification
# ======================================================
echo ""
echo "======================================================"
echo " Verification on $(hostname)"
echo "======================================================"

check() {
    local label=$1
    local cmd=$2
    local result
    result=$(eval "$cmd" 2>/dev/null) && \
        echo "  [OK ] $label: $result" || \
        echo "  [FAIL] $label"
}

check "python3"      "python3 --version"
check "rapidfuzz"    "python3 -c 'import rapidfuzz; print(rapidfuzz.__version__)'"
check "networkx"     "python3 -c 'import networkx; print(networkx.__version__)'"
check "scipy"        "python3 -c 'import scipy; print(scipy.__version__)'"
check "numpy"        "python3 -c 'import numpy; print(numpy.__version__)'"
check "wasm2wat"     "wasm2wat --version 2>&1"
check "wasm-validate" "which wasm-validate"
check "wasm-opt"     "wasm-opt --version 2>&1"
check "wasm-dis"     "which wasm-dis"
check "wasmtime"     "~/.wasmtime/bin/wasmtime --version"
check "wasmer"       "~/.wasmer/bin/wasmer --version"
check "node"         "node --version"
check "npm"          "npm --version"
check "puppeteer"    "NODE_PATH=$PUPPETEER_DIR/node_modules node -e \"require('puppeteer'); console.log('OK')\""

echo ""
echo "To make binaryen 116 available in all future sessions on this node:"
echo "  export PATH=\"$BINARYEN_DIR/bin:\$PATH\""
echo ""
echo "Setup complete on $(hostname)"