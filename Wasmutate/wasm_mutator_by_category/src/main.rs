use std::fs;
use std::path::PathBuf;
use anyhow::{Context, Result};
use clap::Parser;
use rand::Rng;

#[derive(Parser, Debug)]
struct Args {
    /// Input wasm file
    #[clap(long)]
    input: PathBuf,

    /// Output directory for mutants
    #[clap(long, default_value = "mutants")]
    outdir: PathBuf,

    /// Number of different seeds / variants to generate
    #[clap(long, default_value = "5")]
    variants: usize,

    /// Stack depth: how many times apply mutate in chain per variant
    #[clap(long, default_value = "3")]
    stack_depth: usize,

    /// Which meta-rules to enable (comma separated). Example: "peephole,add_function,remove_dead_code"
    #[clap(long, default_value = "peephole,add_function,add_type,remove_dead_code,edit_custom_sections,if_swap,loop_unroll")]
    categories: String,
}

fn main() -> Result<()> {
    let args = Args::parse();

    // Read input wasm
    let wasm_bytes = fs::read(&args.input).context("reading input wasm")?;

    // parse list of categories
    let categories: Vec<&str> = args.categories.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()).collect();

    // Create output dir
    fs::create_dir_all(&args.outdir).context("creating outdir")?;

    // NOTE: the following is pseudocode-ish but matches how you'd configure a Mutator.
    // The concrete API names may differ; adjust according to the crate docs if compile fails.

    // Import the crate types (pseudo)
    // use wasm_mutate::{MutatorConfig, WasmMutate};

    for i in 0..args.variants {
        // choose a seed: either provided or derived
        let seed = {
            let mut rng = rand::thread_rng();
            rng.gen::<u64>() ^ (i as u64 + 0xDEADBEEF)
        };

        // start from original bytes for each variant
        let mut cur = wasm_bytes.clone();

        // Apply stack_depth mutations sequentially
        for level in 0..args.stack_depth {
            // configure mutator for this iteration
            // The API below is illustrative — replace with actual API calls:
            //
            // let mut config = MutatorConfig::default();
            // config.set_seed(seed + level as u64);
            // config.enable_category("peephole", categories.contains(&"peephole"));
            // config.enable_category("add_type", categories.contains(&"add_type"));
            // ...
            //
            // let mut mutator = WasmMutate::new_with_config(&cur, config)?;
            // let out = mutator.run_once()?; // returns Vec<u8>
            //
            // cur = out;

            // ------------------------------
            // ==== Placeholder implementation ====
            // since API may differ, we'll call the CLI `wasm-tools mutate` as a fallback:
            // write cur to a temp file, call wasm-tools mutate --seed <...> -o tmp2.wasm
            // read tmp2.wasm back into cur
            // ------------------------------

            // fallback to call wasm-tools CLI:
            use std::process::Command;
            use std::io::Write;
            let tmp1 = args.outdir.join(format!("tmp_variant_{}_level{}.wasm", i, level));
            let tmp2 = args.outdir.join(format!("tmp_variant_{}_level{}_out.wasm", i, level));
            fs::write(&tmp1, &cur).context("write tmp wasm")?;

            let seed_here = seed.wrapping_add(level as u64);

            let status = Command::new("wasm-tools")
                .arg("mutate")
                .arg(&tmp1)
                .arg("--seed")
                .arg(format!("{}", seed_here))
                .arg("-o")
                .arg(&tmp2)
                .status()
                .context("running wasm-tools mutate")?;

            if !status.success() {
                eprintln!("Warning: wasm-tools mutate failed for variant {} level {} seed {}", i, level, seed_here);
                // keep cur unchanged (skip this mutation)
            } else {
                cur = fs::read(&tmp2).context("read mutated tmp")?;
            }

            // cleanup tmp1/tmp2 helper files optionally
            let _ = fs::remove_file(&tmp1);
            let _ = fs::remove_file(&tmp2);
        }

        // write final mutated wasm
        let out_name = args.outdir.join(format!("{}-mut-{}.wasm", args.input.file_stem().unwrap().to_string_lossy(), i));
        fs::write(&out_name, &cur).context("write final mutant")?;

        println!("Wrote mutant: {} (seed approx {})", out_name.display(), seed);
    }

    Ok(())
}
