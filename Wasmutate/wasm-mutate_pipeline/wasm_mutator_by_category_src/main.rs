use std::fs;
use std::path::PathBuf;
use std::process::Command;

use anyhow::{Context, Result};
use clap::Parser;
use rand::Rng;

/// wasm-mutate's canonical category names (kebab-case, matches
/// MutationCategory's `#[value(rename_all = "kebab-case")]` in the patch).
const VALID_CATEGORIES: &[&str] = &[
    "add-type", "add-function", "edit-custom-sections", "peephole",
    "dead-code-removal", "conditional-swap", "loop-unrolling",
];

#[derive(Parser, Debug)]
struct Args {
    /// Input wasm file
    #[clap(long)]
    input: PathBuf,

    /// Output directory for mutants
    #[clap(long, default_value = "mutants")]
    outdir: PathBuf,

    /// Number of independent mutants to generate
    #[clap(long, default_value = "5")]
    variants: usize,

    /// How many `wasm-tools mutate` applications to chain per variant.
    /// This is the real "intensity" knob of this tool -- unlike
    /// `--categories`, it genuinely changes what's produced: each
    /// additional level re-mutates the previous level's output.
    #[clap(long, default_value = "3")]
    stack_depth: usize,

    /// Only allow semantics-preserving transformations (forwarded verbatim
    /// to `wasm-tools mutate --preserve-semantics`).
    ///
    /// `wasm-tools mutate` defaults this to OFF -- by design it is a
    /// fuzzing / bug-finding tool, free to produce mutants that deliberately
    /// change behavior. Default here is `true` (opposite of wasm-tools
    /// mutate's own default) so that a downstream "payload not preserved"
    /// result reflects a genuine limitation of the transformation rather
    /// than the fuzzer intentionally corrupting the module.
    #[clap(long, default_value_t = true, action = clap::ArgAction::Set)]
    preserve_semantics: bool,

    /// Base RNG seed. If omitted, a random one is drawn and printed to
    /// stdout for every variant, so runs can still be reproduced by
    /// re-supplying the printed seed later.
    #[clap(long)]
    seed: Option<u64>,

    /// Which mutation categories to restrict to (comma-separated). NOW
    /// GENUINELY ENFORCED -- forwarded to `wasm-tools mutate --categories`,
    /// which requires the patched wasm-mutate/wasm-tools from this repo's
    /// `wasm_mutate_patch/` directory (see its README).
    /// Valid values (must match wasm-mutate's MutationCategory exactly):
    ///   add-type, add-function, edit-custom-sections, peephole,
    ///   dead-code-removal, conditional-swap, loop-unrolling
    /// Leave unset (the default, empty list) to draw from wasm-mutate's
    /// full, unrestricted mutator pool -- matches the original, pre-patch
    /// behavior when combined with an unpatched wasm-tools install.
    ///
    /// NOTE: this field is `Vec<String>`, not `Option<String>` -- clap's
    /// `value_delimiter` only actually splits into multiple values for a
    /// collection field type. An earlier version of this wrapper used
    /// `Option<String>` here, which silently kept only the FIRST
    /// comma-separated value and dropped the rest (e.g. `--categories
    /// peephole,if_swap` silently became just `peephole`) -- caught by
    /// testing, not by inspection, which is exactly why it's called out
    /// here explicitly.
    #[clap(long, value_delimiter = ',')]
    categories: Vec<String>,
}

fn main() -> Result<()> {
    let args = Args::parse();

    if !args.categories.is_empty() {
        for c in &args.categories {
            if !VALID_CATEGORIES.contains(&c.as_str()) {
                anyhow::bail!(
                    "unknown category '{c}' -- valid values are: {}",
                    VALID_CATEGORIES.join(", ")
                );
            }
        }
    }

    let wasm_bytes = fs::read(&args.input).context("reading input wasm")?;
    fs::create_dir_all(&args.outdir).context("creating outdir")?;

    let base_seed = args.seed.unwrap_or_else(|| rand::thread_rng().gen::<u64>());

    for i in 0..args.variants {
        // Large odd multiplier spreads consecutive variant indices across
        // the u64 space so nearby `i` values don't produce correlated seeds.
        let variant_seed = base_seed ^ (i as u64).wrapping_mul(0x9E3779B97F4A7C15);

        let mut cur = wasm_bytes.clone();
        let mut applied_levels = 0usize;

        for level in 0..args.stack_depth {
            let tmp1 = args.outdir.join(format!("tmp_variant_{i}_level{level}.wasm"));
            let tmp2 = args.outdir.join(format!("tmp_variant_{i}_level{level}_out.wasm"));
            fs::write(&tmp1, &cur).context("write tmp wasm")?;

            let seed_here = variant_seed.wrapping_add(level as u64);

            let mut cmd = Command::new("wasm-tools");
            cmd.arg("mutate")
                .arg(&tmp1)
                .arg("--seed")
                .arg(format!("{seed_here}"))
                .arg("-o")
                .arg(&tmp2);
            if args.preserve_semantics {
                cmd.arg("--preserve-semantics");
            }
            if let Some(cats) = (!args.categories.is_empty()).then(|| args.categories.join(",")) {
                cmd.arg("--categories").arg(cats);
            }

            let status = cmd.status().context("running wasm-tools mutate")?;

            if !status.success() {
                // Exit code 3 (NoMutationsApplicable after 100 tries) is the
                // common, benign case -- especially likely with
                // --preserve-semantics on a small/simple module, where few
                // mutations qualify. Any other code is worth a louder note.
                let code = status.code().unwrap_or(-1);
                if code == 3 {
                    eprintln!(
                        "note: variant {i} level {level} seed {seed_here}: no applicable \
                         mutation found (exit 3) -- level skipped, input unchanged"
                    );
                } else {
                    eprintln!(
                        "warning: wasm-tools mutate failed for variant {i} level {level} \
                         seed {seed_here} (exit {code}) -- level skipped, input unchanged"
                    );
                }
            } else {
                cur = fs::read(&tmp2).context("read mutated tmp")?;
                applied_levels += 1;
            }

            let _ = fs::remove_file(&tmp1);
            let _ = fs::remove_file(&tmp2);
        }

        let out_name = args
            .outdir
            .join(format!("{}-mut-{}.wasm", args.input.file_stem().unwrap().to_string_lossy(), i));
        fs::write(&out_name, &cur).context("write final mutant")?;

        // Machine-parseable summary line -- the Python pipeline can log
        // this alongside the CSV row for full reproducibility (seed +
        // how many of the requested chain levels actually applied).
        println!(
            "MUTANT path={} variant={} base_seed={} variant_seed={} \
             stack_depth={} applied_levels={} preserve_semantics={} categories={}",
            out_name.display(),
            i,
            base_seed,
            variant_seed,
            args.stack_depth,
            applied_levels,
            args.preserve_semantics,
            if args.categories.is_empty() { "(unrestricted)".to_string() } else { args.categories.join(",") },
        );
    }

    Ok(())
}
