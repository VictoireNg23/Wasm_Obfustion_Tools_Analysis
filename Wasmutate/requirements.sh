#!/bin/bash
# =======================
# requirements.sh
# Installe tout le nécessaire pour exécuter les scripts WasmMutate
# =======================

set -e

echo "=== Mise à jour des paquets ==="
sudo apt update
sudo apt upgrade -y

echo "=== Installer les dépendances système pour Rust et Node.js ==="
sudo apt install -y curl build-essential wget git python3 python3-pip

echo "=== Installer Rust et Cargo ==="
if ! command -v cargo &>/dev/null; then
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source $HOME/.cargo/env
else
    echo "Rust déjà installé"
fi

echo "=== Installer les outils WebAssembly ==="
sudo apt install -y wasm-tools wabt binaryen wasmtime

echo "=== Installer Node.js et npm ==="
sudo apt install -y nodejs npm

echo "=== Installer les librairies pour Puppeteer (Chromium) ==="
sudo apt install -y gconf-service libasound2 libatk1.0-0 libc6 libcairo2 libcups2 \
libdbus-1-3 libexpat1 libfontconfig1 libgcc1 libgconf-2-4 libgdk-pixbuf2.0-0 \
libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 libx11-xcb1 \
libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 \
libxrandr2 libxrender1 libxss1 libxtst6 ca-certificates fonts-liberation \
libappindicator1 libnss3 lsb-release xdg-utils wget

echo "=== Installer Puppeteer et minimist ==="
npm install -g puppeteer minimist

echo "=== Compilation du mutator Rust ==="
MUTATOR_DIR="$HOME/Téléchargements/wasm/SOK/Wasmutate/wasm_mutator_by_category"
if [[ -d "$MUTATOR_DIR" ]]; then
    cd "$MUTATOR_DIR"
    cargo build --release
    echo "Binaire compilé dans $MUTATOR_DIR/target/release/wasm_mutator_by_category"
else
    echo "Dossier du mutator non trouvé: $MUTATOR_DIR"
fi

echo "=== Vérifications ==="
command -v wasm2wat || echo "wasm2wat manquant"
command -v wasm-tools || echo "wasm-tools manquant"
command -v wasm-opt || echo "wasm-opt manquant"
command -v wasmtime || echo "wasmtime manquant"
command -v cargo || echo "cargo manquant"
command -v node || echo "node manquant"
command -v npm || echo "npm manquant"

echo "=== Tout est installé ! ==="

# chmod +x requirements.sh
# ./requirements.sh
