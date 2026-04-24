#!/usr/bin/env node
/**
 * run_browser_test.js
 *
 * Usage:
 * node run_browser_test.js --wasm /full/path/to/file.wasm --outdir /path/to/outdir --inputs '[[1,2],[5,7]]'
 *
 * Captures:
 * - logs console
 * - exports results
 * - memory snapshot
 * - saves JSON into outdir/browser_state.json
 */

const fs = require('fs');
const path = require('path');
const puppeteer = require('puppeteer');
const argv = require('minimist')(process.argv.slice(2));

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function main() {
  const wasmPath = argv.wasm;
  const outdir = argv.outdir || '.';
  const inputs = argv.inputs ? JSON.parse(argv.inputs) : [];

  if (!wasmPath) { console.error("Missing --wasm argument"); process.exit(2); }
  if (!fs.existsSync(wasmPath)) { console.error("WASM file not found:", wasmPath); process.exit(3); }
  if (!fs.existsSync(outdir)) fs.mkdirSync(outdir, { recursive: true });

  const wasmBuf = fs.readFileSync(wasmPath);
  const b64 = wasmBuf.toString('base64');

  const browser = await puppeteer.launch({ args: ['--no-sandbox','--disable-setuid-sandbox'] });
  const page = await browser.newPage();

  const logs = [];
  page.on('console', msg => logs.push({type:'console', text: msg.text()}));
  page.on('pageerror', err => logs.push({type:'pageerror', text: err.toString()}));
  page.on('error', err => logs.push({type:'error', text: err.toString()}));

  await page.evaluateOnNewDocument((base64, inputs) => {
    window.__WASM_BASE64__ = base64;
    window.__WASM_INPUTS__ = inputs;
  }, b64, inputs);

  const html = `
    <!doctype html>
    <html>
    <body>
      <script>
        (async () => {
          const out = { logs: [], outputs: [], exports: [], memory_snapshot: null, error: null };
          try {
            const bin = Uint8Array.from(atob(window.__WASM_BASE64__), c => c.charCodeAt(0));
            const imports = {
              env: {
                memoryBase: 0,
                tableBase: 0,
                memory: new WebAssembly.Memory({initial:256, maximum:4096}),
                table: new WebAssembly.Table({initial:0, element:'anyfunc'}),
                abort: () => { throw new Error('abort called'); },
                _emscripten_memcpy_big: () => 0
              },
              wasi_snapshot_preview1: {}
            };
            const { instance } = await WebAssembly.instantiate(bin, imports);
            const exports = instance.exports || {};
            out.exports = Object.keys(exports);

            for (let arr of (window.__WASM_INPUTS__ || [])) {
              try {
                if (typeof exports.main === 'function') {
                  out.outputs.push({input: arr, result: String(exports.main.apply(null, arr))});
                } else {
                  const fName = out.exports.find(n => typeof exports[n] === 'function');
                  if (fName) out.outputs.push({input: [], called: fName, result: String(exports[fName]())});
                  else out.outputs.push({input: [], result: "no-callable-export"});
                }
              } catch (e) { out.outputs.push({input: arr, error: String(e)}); }
            }

            try {
              if (imports.env.memory) {
                const mem = new Uint8Array(imports.env.memory.buffer);
                out.memory_snapshot = Array.from(mem.slice(0, Math.min(512, mem.length))).join(',');
              }
            } catch(e) { out.memory_snapshot = "MEM_ERROR:"+String(e); }

            window.__BROWSER_STATE__ = out;
          } catch (err) {
            window.__BROWSER_STATE__ = { logs: [], outputs: [], exports: [], memory_snapshot: null, error: String(err) };
            console.error('PAGE ERROR', err);
          }
        })();
      </script>
    </body>
    </html>
  `;

  await page.setContent(html, { waitUntil: 'load' });
  await sleep(1200);

  let state = await page.evaluate(() => window.__BROWSER_STATE__ || { logs: [], outputs: [], exports: [], memory_snapshot: null, error: "NO_STATE" });
  state.raw_console = logs;

  const outFile = path.join(outdir, 'browser_state.json');
  fs.writeFileSync(outFile, JSON.stringify(state, null, 2), 'utf8');

  await browser.close();
  console.log("WROTE", outFile);
  process.exit(0);
}

main().catch(err => { console.error(err); process.exit(1); });
