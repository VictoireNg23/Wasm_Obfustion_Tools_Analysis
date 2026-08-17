#!/usr/bin/env node
// browser_runner.js
/**
 * Execute a WebAssembly module in a real Chromium environment (via Puppeteer)
 * and capture two independent behavioral signals:
 *
 *   1. state_hash        -- SHA-256 of linear memory after execution.
 *   2. import_trace_hash -- SHA-256 of the ordered sequence of all host API
 *                           calls made by the module + their arguments.
 *
 * Compatible with:
 *   - Node.js >= 12.22
 *   - Puppeteer 14.x  (npm install puppeteer@14.4.1)
 *   - Headless Chromium on Linux compute nodes (no GPU, no display)
 *
 * Parses the Wasm binary import section to extract the exact type, mutability,
 * and size requirements for every imported global, memory, and table, so that
 * WebAssembly.instantiate never fails with type/size mismatch errors.
 *
 * Usage:
 *   NODE_PATH=/tmp/puppeteer_env/node_modules \
 *     node browser_runner.js --wasm <file.wasm> [--timeout-ms 15000] [--out result.json]
 *
 * Output (stdout, last line, JSON):
 * {
 *   "wasm_path":         string,
 *   "state_hash":        string | null,
 *   "import_trace_hash": string | null,
 *   "import_trace":      [{fn, args}],
 *   "memory_pages":      number | null,
 *   "exports_called":    [string],
 *   "runtime_ms":        number,
 *   "error":             string | null
 * }
 */

"use strict";

const fs     = require("fs");
const path   = require("path");
const crypto = require("crypto");

const argv = process.argv.slice(2);
function getArg(flag) {
    const i = argv.indexOf(flag);
    return i !== -1 ? argv[i + 1] : null;
}

const wasmPath  = getArg("--wasm");
const timeoutMs = parseInt(getArg("--timeout-ms") || "15000", 10);
const outPath   = getArg("--out");

if (!wasmPath) {
    console.error("Usage: node browser_runner.js --wasm <file.wasm> [--timeout-ms N] [--out result.json]");
    process.exit(1);
}

function sha256hex(data) {
    return crypto.createHash("sha256").update(data).digest("hex");
}

function outputResult(result) {
    const json = JSON.stringify(result);
    if (outPath) { try { fs.writeFileSync(outPath, json); } catch(e) {} }
    console.log(json);
}

async function run() {
    const startMs = Date.now();

    let wasmBytes;
    try {
        wasmBytes = fs.readFileSync(path.resolve(wasmPath));
    } catch(e) {
        outputResult({ wasm_path: wasmPath, error: "read_failed:" + e.message,
            state_hash: null, import_trace_hash: null,
            import_trace: [], memory_pages: null, exports_called: [], runtime_ms: 0 });
        return;
    }

    let puppeteer;
    try { puppeteer = require("puppeteer"); }
    catch(e) {
        outputResult({ wasm_path: wasmPath, error: "puppeteer_not_installed",
            state_hash: null, import_trace_hash: null,
            import_trace: [], memory_pages: null, exports_called: [], runtime_ms: 0 });
        return;
    }

    let browser;
    try {
        browser = await puppeteer.launch({
            headless: true,
            args: [
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-software-rasterizer", "--no-zygote",
                "--single-process", "--disable-extensions",
                "--disable-background-networking", "--disable-default-apps",
            ],
        });
    } catch(e) {
        outputResult({ wasm_path: wasmPath, error: "browser_launch_failed:" + e.message,
            state_hash: null, import_trace_hash: null,
            import_trace: [], memory_pages: null, exports_called: [], runtime_ms: 0 });
        return;
    }

    let result;
    try {
        const page = await browser.newPage();
        page.on("console", function(){});
        page.on("pageerror", function(){});

        const wasmB64 = wasmBytes.toString("base64");

        result = await page.evaluate(async function(wasmB64, timeoutMs) {

            // ---- helpers ----
            function sha256hex(buffer) {
                // Pure JS SHA-256 -- works in any context (no crypto.subtle needed)
                var bytes = new Uint8Array(buffer);
                var data = Array.from(bytes);
                var K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,
                          0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
                          0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
                          0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
                          0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
                          0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
                          0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,
                          0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
                          0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
                          0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
                          0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,
                          0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
                          0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,
                          0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
                          0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
                          0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
                var H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                         0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
                data.push(0x80);
                while (data.length % 64 !== 56) data.push(0);
                var len = bytes.length * 8;
                for (var i = 7; i >= 0; i--) { data.push(len & 0xff); len = Math.floor(len / 256); }
                function rotr(x,n){return (x>>>n)|(x<<(32-n));}
                for (var i = 0; i < data.length; i += 64) {
                    var w = [];
                    for (var j = 0; j < 16; j++)
                        w[j] = (data[i+j*4]<<24)|(data[i+j*4+1]<<16)|(data[i+j*4+2]<<8)|data[i+j*4+3];
                    for (var j = 16; j < 64; j++) {
                        var s0=rotr(w[j-15],7)^rotr(w[j-15],18)^(w[j-15]>>>3);
                        var s1=rotr(w[j-2],17)^rotr(w[j-2],19)^(w[j-2]>>>10);
                        w[j]=(w[j-16]+s0+w[j-7]+s1)>>>0;
                    }
                    var a=H[0],b=H[1],c=H[2],d=H[3],e=H[4],f=H[5],g=H[6],h=H[7];
                    for (var j = 0; j < 64; j++) {
                        var S1=rotr(e,6)^rotr(e,11)^rotr(e,25);
                        var ch=(e&f)^(~e&g);
                        var temp1=(h+S1+ch+K[j]+w[j])>>>0;
                        var S0=rotr(a,2)^rotr(a,13)^rotr(a,22);
                        var maj=(a&b)^(a&c)^(b&c);
                        var temp2=(S0+maj)>>>0;
                        h=g;g=f;f=e;e=(d+temp1)>>>0;d=c;c=b;b=a;a=(temp1+temp2)>>>0;
                    }
                    H[0]=(H[0]+a)>>>0;H[1]=(H[1]+b)>>>0;H[2]=(H[2]+c)>>>0;H[3]=(H[3]+d)>>>0;
                    H[4]=(H[4]+e)>>>0;H[5]=(H[5]+f)>>>0;H[6]=(H[6]+g)>>>0;H[7]=(H[7]+h)>>>0;
                }
                return H.map(function(x){return ('00000000'+x.toString(16)).slice(-8);}).join('');
            }

            function b64toUint8(b64) {
                var bin = atob(b64);
                var buf = new Uint8Array(bin.length);
                for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
                return buf;
            }

            var wasmBytes = b64toUint8(wasmB64);

            // ----------------------------------------------------------------
            // Wasm binary import section parser
            // Extracts exact type, mutability, and size for every import so
            // WebAssembly.Global / Memory / Table are always created correctly.
            // ----------------------------------------------------------------
            function readLEB128(bytes, offset) {
                var result = 0, shift = 0, b;
                do { b = bytes[offset++]; result |= (b & 0x7F) << shift; shift += 7; }
                while (b & 0x80);
                return { value: result, offset: offset };
            }

            function readString(bytes, offset) {
                var len = readLEB128(bytes, offset); offset = len.offset;
                var s = "";
                for (var i = 0; i < len.value; i++) s += String.fromCharCode(bytes[offset++]);
                return { value: s, offset: offset };
            }

            function parseImportSection(bytes) {
                // Returns { globals: {}, memories: {}, tables: {} }
                // globals  : { "mod.name": { valueType: "i32"|"i64"|"f32"|"f64", mutable: bool } }
                // memories : { "mod.name": { initial: N, maximum: N|undefined } }
                // tables   : { "mod.name": { initial: N, maximum: N|undefined } }
                var globals  = {};
                var memories = {};
                var tables   = {};

                var i = 8; // skip magic + version
                while (i < bytes.length) {
                    var sectionId   = bytes[i++];
                    var sectionSize = readLEB128(bytes, i); i = sectionSize.offset;
                    var sectionEnd  = i + sectionSize.value;

                    if (sectionId !== 2) { i = sectionEnd; continue; } // not import section

                    var countR = readLEB128(bytes, i); i = countR.offset;
                    for (var n = 0; n < countR.value && i < sectionEnd; n++) {
                        var modR  = readString(bytes, i); i = modR.offset;
                        var nameR = readString(bytes, i); i = nameR.offset;
                        var kind  = bytes[i++];
                        var key   = modR.value + "." + nameR.value;

                        if (kind === 0) {
                            // function: skip type index (LEB128)
                            var r = readLEB128(bytes, i); i = r.offset;
                        } else if (kind === 1) {
                            // table: reftype (1 byte) + limits
                            i++; // reftype
                            var flags = bytes[i++];
                            var minR  = readLEB128(bytes, i); i = minR.offset;
                            var maxVal = undefined;
                            if (flags & 1) { var maxR = readLEB128(bytes, i); i = maxR.offset; maxVal = maxR.value; }
                            tables[key] = { initial: minR.value, maximum: maxVal };
                        } else if (kind === 2) {
                            // memory: limits
                            var flags = bytes[i++];
                            var minR  = readLEB128(bytes, i); i = minR.offset;
                            var maxVal = undefined;
                            if (flags & 1) { var maxR = readLEB128(bytes, i); i = maxR.offset; maxVal = maxR.value; }
                            memories[key] = { initial: minR.value, maximum: maxVal };
                        } else if (kind === 3) {
                            // global: value type (1 byte) + mutability (1 byte)
                            var valTypeByte = bytes[i++];
                            var mutByte     = bytes[i++];
                            var typeMap = { 0x7F:"i32", 0x7E:"i64", 0x7D:"f32", 0x7C:"f64" };
                            globals[key] = {
                                valueType: typeMap[valTypeByte] || "i32",
                                mutable:   mutByte === 1
                            };
                        }
                    }
                    break; // import section always comes first; stop here
                }
                return { globals: globals, memories: memories, tables: tables };
            }

            var importInfo = parseImportSection(wasmBytes);
            var globalTypes  = importInfo.globals;
            var memoryTypes  = importInfo.memories;
            var tableTypes   = importInfo.tables;

            // ---- import trace ----
            var importTrace = [];
            var MAX_TRACE   = 500;
            var ARGS_LIMIT  = 8;
            var ARG_STR_LIM = 64;

            function traceArg(a) {
                if (a === null || a === undefined) return null;
                if (typeof a === "number" || typeof a === "bigint") return String(a);
                if (typeof a === "string") return a.slice(0, ARG_STR_LIM);
                return typeof a;
            }

            // ---- universal import proxy ----
            function makeNamespaceProxy(ns) {
                return new Proxy({}, {
                    get: function(_, key) {
                        var skey    = String(key);
                        var fullKey = ns + "." + skey;

                        // memory: use exact initial size from binary
                        if (memoryTypes[fullKey]) {
                            var mi = memoryTypes[fullKey];
                            var maxPages = mi.maximum !== undefined
                                ? mi.maximum
                                : Math.min(mi.initial * 2 + 256, 65536);
                            return new WebAssembly.Memory({
                                initial: mi.initial,
                                maximum: maxPages
                            });
                        }
                        // fallback memory detection by name
                        if (skey === "memory")
                            return new WebAssembly.Memory({ initial: 256, maximum: 65536 });

                        // table: use exact initial size from binary
                        if (tableTypes[fullKey]) {
                            var ti = tableTypes[fullKey];
                            // Use maximum as initial so element initializers never go out of bounds
                            var tableSize = ti.maximum !== undefined ? ti.maximum : Math.max(ti.initial, 65536);
                            return new WebAssembly.Table({ initial: tableSize, maximum: tableSize, element: "anyfunc" });
                        }
                        if (skey === "table" || skey === "__indirect_function_table")
                            return new WebAssembly.Table({ initial: 0, element: "anyfunc" });

                        // global: use exact type + mutability from binary
                        if (globalTypes[fullKey]) {
                            var gi = globalTypes[fullKey];
                            var iv = (gi.valueType === "f32" || gi.valueType === "f64") ? 0.0 : 0;
                            return new WebAssembly.Global({ value: gi.valueType, mutable: gi.mutable }, iv);
                        }

                        // default: tracing function stub
                        return function() {
                            var args = Array.prototype.slice.call(arguments, 0, ARGS_LIMIT);
                            if (importTrace.length < MAX_TRACE)
                                importTrace.push({ fn: fullKey, args: args.map(traceArg) });
                            return 0;
                        };
                    }
                });
            }

            // outer proxy: catches ANY undeclared namespace automatically
            var proxiedImports = new Proxy({}, {
                get: function(_, ns) { return makeNamespaceProxy(String(ns)); }
            });

            // ---- compile + instantiate ----
            var moduleObj;
            try { moduleObj = await WebAssembly.compile(wasmBytes); }
            catch(e) {
                return { error: "compile_failed:" + e.message,
                    state_hash: null, import_trace_hash: null,
                    import_trace: [], memory_pages: null, exports_called: [] };
            }

            var instance;
            try { instance = await WebAssembly.instantiate(moduleObj, proxiedImports); }
            catch(e) {
                return { error: "instantiate_failed:" + e.message,
                    state_hash: null, import_trace_hash: null,
                    import_trace: importTrace.slice(0, 50),
                    memory_pages: null, exports_called: [] };
            }

            // ---- execute ----
            var exports_called = [];
            var ENTRY_NAMES = ["_start", "main", "_main", "start", "__wasm_call_ctors"];

            function tryInvoke(name, fn) {
                return new Promise(function(resolve) {
                    try {
                        if (typeof fn !== "function") { resolve(); return; }
                        var ret = fn();
                        if (ret && typeof ret.then === "function") {
                            var timer = setTimeout(function() {
                                exports_called.push(name + ":timeout"); resolve();
                            }, timeoutMs);
                            ret.then(function() {
                                clearTimeout(timer); exports_called.push(name); resolve();
                            }, function(e) {
                                clearTimeout(timer);
                                exports_called.push(name + ":err:" + String(e).slice(0, 60));
                                resolve();
                            });
                        } else { exports_called.push(name); resolve(); }
                    } catch(e) {
                        exports_called.push(name + ":err:" + String(e).slice(0, 60)); resolve();
                    }
                });
            }

            var entryPromise = Promise.resolve();
            var foundEntry   = false;
            for (var i = 0; i < ENTRY_NAMES.length; i++) {
                if (instance.exports[ENTRY_NAMES[i]]) {
                    foundEntry   = true;
                    entryPromise = tryInvoke(ENTRY_NAMES[i], instance.exports[ENTRY_NAMES[i]]);
                    break;
                }
            }
            if (!foundEntry) {
                var expKeys = Object.keys(instance.exports);
                for (var j = 0; j < expKeys.length; j++) {
                    if (typeof instance.exports[expKeys[j]] === "function") {
                        entryPromise = tryInvoke(expKeys[j], instance.exports[expKeys[j]]);
                        break;
                    }
                }
            }
            await entryPromise;

            // ---- capture memory state ----
            var memExport = instance.exports.memory;
            if (!memExport) {
                var expKeys2 = Object.keys(instance.exports);
                for (var k = 0; k < expKeys2.length; k++) {
                    if (instance.exports[expKeys2[k]] instanceof WebAssembly.Memory) {
                        memExport = instance.exports[expKeys2[k]]; break;
                    }
                }
            }

            var memoryPages = null;
            var stateHash   = null;
            if (memExport) {
                try {
                    var memView = new Uint8Array(memExport.buffer);
                    memoryPages = memExport.buffer.byteLength / 65536;
                    var snapLen = Math.min(memView.length, 4 * 1024 * 1024);
                    stateHash   = await sha256hex(memView.slice(0, snapLen).buffer);
                } catch(e) { stateHash = null; }
            }

            // ---- hash import trace ----
            var traceStr   = JSON.stringify(importTrace);
            var traceBytes = new TextEncoder().encode(traceStr);
            var traceHash  = await sha256hex(traceBytes.buffer);

            return {
                error:             null,
                state_hash:        stateHash,
                import_trace_hash: traceHash,
                import_trace:      importTrace.slice(0, 200),
                memory_pages:      memoryPages,
                exports_called:    exports_called
            };

        }, wasmB64, timeoutMs);

    } catch(e) {
        result = { error: "page_eval_failed:" + e.message,
            state_hash: null, import_trace_hash: null,
            import_trace: [], memory_pages: null, exports_called: [] };
    } finally {
        try { await browser.close(); } catch(_) {}
    }

    result.wasm_path  = wasmPath;
    result.runtime_ms = Date.now() - startMs;
    outputResult(result);
}

run().catch(function(e) {
    outputResult({ wasm_path: wasmPath, error: "uncaught:" + e.message,
        state_hash: null, import_trace_hash: null,
        import_trace: [], memory_pages: null, exports_called: [], runtime_ms: 0 });
});
