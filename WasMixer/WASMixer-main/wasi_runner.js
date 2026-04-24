const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const argv = require("minimist")(process.argv.slice(2), {
  string: ["wasm", "invoke", "out"],
  default: { invoke: "" }
});

const { WASI } = require("@wasmer/wasi");
const { WasmFs } = require("@wasmer/wasmfs");

async function run() {
  if (!argv.wasm) {
    console.error("Missing --wasm");
    process.exit(1);
  }

  const wasmPath = path.resolve(argv.wasm);
  const wasmBytes = fs.readFileSync(wasmPath);

  const result = {
    ok: false,
    error: null,
    exports: {},
    imports: [],
    return_value: null,
    memory_size: null,
    memory_hash: null,
    instantiate_ms: null,
    exec_ms: null
  };

  try {
    const wasmFs = new WasmFs();
    const wasi = new WASI({
      args: [],
      env: {},
      bindings: {
        ...WASI.defaultBindings,
        fs: wasmFs.fs
      }
    });

    const module = await WebAssembly.compile(wasmBytes);
    result.imports = WebAssembly.Module.imports(module);

    const t0 = performance.now();
    const instance = await WebAssembly.instantiate(module, wasi.getImportObject());
    const t1 = performance.now();

    wasi.start(instance);
    result.instantiate_ms = t1 - t0;

    const exp = instance.exports;

    for (const k of Object.keys(exp)) {
      result.exports[k] = typeof exp[k];
    }

    // call main if exists
    if (exp._start) {
      const e0 = performance.now();
      exp._start();
      const e1 = performance.now();
      result.exec_ms = e1 - e0;
      result.ok = true;
    } else if (exp.main) {
      const e0 = performance.now();
      const r = exp.main();
      const e1 = performance.now();
      result.exec_ms = e1 - e0;
      result.return_value = r;
      result.ok = true;
    }

    if (exp.memory) {
      const mem = new Uint8Array(exp.memory.buffer);
      result.memory_size = mem.length;
      let h = 0;
      for (let i = 0; i < Math.min(mem.length, 4096); i++) {
        h = ((h << 5) - h) + mem[i];
        h |= 0;
      }
      result.memory_hash = h;
    }

  } catch (e) {
    result.error = String(e);
  }

  const stable = JSON.stringify(result, Object.keys(result).sort());
  result.state_hash = crypto.createHash("sha256").update(stable).digest("hex");

  if (argv.out) {
    fs.writeFileSync(argv.out, JSON.stringify(result, null, 2));
  }

  console.log(JSON.stringify(result));
}

run();
