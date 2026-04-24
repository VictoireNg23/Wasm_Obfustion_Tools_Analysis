// tools/browser_runner.js
// Puppeteer runner for WASM (headless Chrome) with a basic WASI shim
// Usage:
//   node tools/browser_runner.js --wasm /path/to/module.wasm [--invoke main] [--timeout-ms 5000] [--out /tmp/result.json]
//
// Requires: npm install puppeteer minimist
//
// Output: prints a single JSON object to stdout (one line) and optionally writes to --out

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const puppeteer = require("puppeteer");
const argv = require("minimist")(process.argv.slice(2), {
  string: ["wasm", "invoke", "out"],
  default: { invoke: "", "timeout-ms": 8000 }
});

// WASI runtime
const { WASI } = require("@wasmer/wasi");
const { WasmFs } = require("@wasmer/wasmfs");

async function run() {
  if (!argv.wasm) {
    console.error("Missing --wasm");
    process.exit(1);
  }

  const wasmPath = path.resolve(argv.wasm);
  if (!fs.existsSync(wasmPath)) {
    console.error("WASM file not found:", wasmPath);
    process.exit(1);
  }

  const wasmBuffer = fs.readFileSync(wasmPath);
  const wasmBase64 = wasmBuffer.toString("base64");

  const browser = await puppeteer.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"]
  });
  const page = await browser.newPage();

  const result = await page.evaluate(
    async (wasmB64, invoke) => {
      function b64ToBytes(b64) {
        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        return bytes;
      }

      const report = {
        ok: false,
        error: null,
        exports: {},
        imports: [],
        return_value: null,
        memory_size: null,
        memory_hash: null,
        instantiate_ms: null,
        exec_ms: null,
        logs: []
      };

      try {
        const bytes = b64ToBytes(wasmB64);

        // ===== Créer WASI + filesystem =====
        const { WASI } = require("@wasmer/wasi");
        const { WasmFs } = require("@wasmer/wasmfs");
        const wasmFs = new WasmFs();

        const wasi = new WASI({
          args: [],
          env: {},
          bindings: {
            ...WASI.defaultBindings,
            fs: wasmFs.fs
          }
        });

        const mod = await WebAssembly.compile(bytes);
        const t0 = performance.now();
        const instance = await WebAssembly.instantiate(mod, {
          ...wasi.getImportObject()
        });
        wasi.start(instance);
        const t1 = performance.now();
        report.instantiate_ms = t1 - t0;

        // Exports
        report.exports = Object.keys(instance.exports).reduce((acc, k) => {
          const v = instance.exports[k];
          acc[k] = typeof v === "function" ? "function" : typeof v;
          return acc;
        }, {});

        // Execute function
        let fn = null;
        if (invoke && instance.exports[invoke]) fn = instance.exports[invoke];
        else if (instance.exports.main) fn = instance.exports.main;
        else {
          for (const k of Object.keys(instance.exports)) {
            if (typeof instance.exports[k] === "function") {
              fn = instance.exports[k];
              break;
            }
          }
        }

        if (fn) {
          const e0 = performance.now();
          const ret = fn();
          const e1 = performance.now();
          report.exec_ms = e1 - e0;
          report.return_value = ret === undefined ? null : ret;
          report.ok = true;
        }

        // Memory snapshot
        if (instance.exports.memory) {
          const mem = new Uint8Array(instance.exports.memory.buffer);
          report.memory_size = mem.length;
          let h = 0;
          for (let i = 0; i < Math.min(mem.length, 4096); i++) {
            h = ((h << 5) - h) + mem[i];
            h |= 0;
          }
          report.memory_hash = h;
        }
      } catch (e) {
        report.error = e.toString();
      }

      return report;
    },
    wasmBase64,
    argv.invoke
  );

  await browser.close();

  // Stable hash
  const stable = JSON.stringify(result, Object.keys(result).sort());
  result.state_hash = crypto.createHash("sha256").update(stable).digest("hex");

  if (argv.out) {
    fs.writeFileSync(argv.out, JSON.stringify(result, null, 2));
  }

  console.log(JSON.stringify(result));
}

run();
