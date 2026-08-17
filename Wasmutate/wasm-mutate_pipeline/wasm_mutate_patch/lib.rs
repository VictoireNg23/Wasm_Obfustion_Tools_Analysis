//! A WebAssembly test case mutator.
//!
//! `wasm-mutate` takes in an existing Wasm module and then applies a
//! pseudo-random transformation to it, producing a new, mutated Wasm
//! module. This new, mutated Wasm module can be fed as a test input to your
//! Wasm parser, validator, compiler, or any other Wasm-consuming
//! tool. `wasm-mutate` can serve as a custom mutator for mutation-based
//! fuzzing.

#![cfg_attr(not(feature = "clap"), deny(missing_docs))]

mod error;
mod info;
mod module;
mod mutators;

pub use error::*;

use crate::mutators::{
    Item, add_function::AddFunctionMutator, add_type::AddTypeMutator,
    codemotion::CodemotionMutator, codemotion::IfSwapMutator, codemotion::LoopUnrollOnlyMutator,
    custom::AddCustomSectionMutator, custom::CustomSectionMutator,
    custom::ReorderCustomSectionMutator, function_body_unreachable::FunctionBodyUnreachable,
    modify_const_exprs::ConstExpressionMutator, modify_data::ModifyDataMutator,
    peephole::PeepholeMutator, remove_export::RemoveExportMutator, remove_item::RemoveItemMutator,
    remove_section::RemoveSection, rename_export::RenameExportMutator, snip_function::SnipMutator,
    start::RemoveStartSection,
};
use info::ModuleInfo;
use mutators::Mutator;
use rand::{RngExt, SeedableRng, rngs::SmallRng};
use std::sync::Arc;

#[cfg(feature = "clap")]
use clap::Parser;

/// One of the seven named mutation categories exposed for external,
/// per-category selection via `WasmMutate::categories` /
/// `wasm-tools mutate --categories`.
///
/// This is an ADDITION on top of wasm-mutate's original design: by
/// default (see `run()`), wasm-mutate picks uniformly at random among its
/// full internal mutator pool with no category concept at all. Grouping
/// them into these seven categories is a deliberate simplification for
/// comparative obfuscation-evaluation purposes, not something inherent to
/// wasm-mutate's own design -- several
/// internal mutators (RemoveExportMutator, RenameExportMutator,
/// ConstExpressionMutator, ModifyDataMutator) don't fit any of the seven
/// categories and remain reachable only when `categories` is left empty
/// (the original, fully-unrestricted mode).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[cfg_attr(feature = "clap", derive(clap::ValueEnum))]
#[cfg_attr(feature = "clap", value(rename_all = "kebab-case"))]
pub enum MutationCategory {
    /// I1: adds unused, randomly-shaped type signatures.
    /// CLI value: `add-type`
    AddType,
    /// I2: adds dummy functions.
    /// CLI value: `add-function`
    AddFunction,
    /// I3: modifies or adds custom sections.
    /// CLI value: `edit-custom-sections`
    EditCustomSections,
    /// I4: rewrites local instruction sequences via equivalence rules.
    /// CLI value: `peephole`
    Peephole,
    /// I5: removes entities validated as dead (functions, types, imports,
    /// globals, data segments, custom sections, the start section, etc.).
    /// CLI value: `dead-code-removal`
    DeadCodeRemoval,
    /// I6: swaps conditional branches (if/else complement).
    /// CLI value: `conditional-swap`
    ConditionalSwap,
    /// I7: unrolls loop constructs.
    /// CLI value: `loop-unrolling`
    LoopUnrolling,
}

// NB: only add this doc comment if we are not building the CLI, since otherwise
// it will override the main CLI's about text.
#[cfg_attr(
    not(feature = "clap"),
    doc = r###"
A WebAssembly test case mutator.

This is the main entry point into this crate. It provides various methods for
configuring what kinds of mutations might be applied to the input Wasm. Once
configured, you can apply a transformation to the input Wasm via the
[`run`][crate::WasmMutate::run] method.

# Example

```
# fn _foo() -> anyhow::Result<()> {
use wasm_mutate::WasmMutate;

let input_wasm = wat::parse_str(r#"
           (module
            (func (export "hello") (result i32)
             (i32.const 1234)
            )
           )
           "#)?;

// Create a `WasmMutate` builder and configure it.
let mut mutate = WasmMutate::default();
mutate
    // Set the RNG seed.
    .seed(42)
    // Allow mutations that change the semantics of the Wasm module.
    .preserve_semantics(false)
    // Use at most this much "fuel" when trying to mutate the Wasm module before
    // giving up.
    .fuel(1_000);

// Run the configured `WasmMutate` to get a sequence of mutations of the input
// Wasm!
for mutated_wasm in mutate.run(&input_wasm)? {
    let mutated_wasm = mutated_wasm?;
    // Feed `mutated_wasm` into your tests...
}
# Ok(())
# }
```
"###
)]
#[cfg_attr(feature = "clap", derive(Parser))]
#[derive(Clone)]
pub struct WasmMutate<'wasm> {
    /// The RNG seed used to choose which transformation to apply. Given the
    /// same input Wasm and same seed, `wasm-mutate` will always generate the
    /// same output Wasm.
    #[cfg_attr(feature = "clap", clap(short, long, default_value = "42"))]
    seed: u64,

    /// Only perform semantics-preserving transformations on the Wasm module.
    #[cfg_attr(feature = "clap", clap(long))]
    preserve_semantics: bool,

    /// Fuel to control the time of the mutation.
    #[cfg_attr(
        feature = "clap",
        clap(
            short,
            long,
            default_value = "18446744073709551615", // u64::MAX
        )
    )]
    fuel: u64,

    /// Only perform size-reducing transformations on the Wasm module. This
    /// allows `wasm-mutate` to be used as a test case reducer.
    #[cfg_attr(feature = "clap", clap(long))]
    reduce: bool,

    /// Restrict mutation to one or more named categories (see
    /// `MutationCategory`). Left empty (the default), all of
    /// wasm-mutate's built-in mutators are eligible, exactly as before
    /// this field existed -- this is purely additive and changes nothing
    /// about the default/unfiltered behavior.
    #[cfg_attr(feature = "clap", clap(long, value_delimiter = ','))]
    categories: Vec<MutationCategory>,

    // Note: this is only exposed via the programmatic interface, not via the
    // CLI.
    #[cfg_attr(feature = "clap", clap(skip = None))]
    raw_mutate_func: Option<Arc<dyn Fn(&mut Vec<u8>, usize) -> Result<()>>>,

    #[cfg_attr(feature = "clap", clap(skip = None))]
    rng: Option<SmallRng>,

    #[cfg_attr(feature = "clap", clap(skip = None))]
    info: Option<ModuleInfo<'wasm>>,
}

impl Default for WasmMutate<'_> {
    fn default() -> Self {
        let seed = 3;
        WasmMutate {
            seed,
            preserve_semantics: false,
            reduce: false,
            categories: Vec::new(),
            raw_mutate_func: None,
            fuel: u64::MAX,
            rng: None,
            info: None,
        }
    }
}

impl<'wasm> WasmMutate<'wasm> {
    /// Set the RNG seed used to choose which transformation to apply.
    ///
    /// Given the same input Wasm and same seed, `wasm-mutate` will always
    /// generate the same output Wasm.
    pub fn seed(&mut self, seed: u64) -> &mut Self {
        self.seed = seed;
        self
    }

    /// Configure whether we will only perform semantics-preserving
    /// transformations on the Wasm module.
    pub fn preserve_semantics(&mut self, preserve_semantics: bool) -> &mut Self {
        self.preserve_semantics = preserve_semantics;
        self
    }

    /// Configure the fuel used during the mutation
    pub fn fuel(&mut self, fuel: u64) -> &mut Self {
        self.fuel = fuel;
        self
    }

    /// Configure whether we will only perform size-reducing transformations on
    /// the Wasm module.
    ///
    /// Setting this to `true` allows `wasm-mutate` to be used as a test case
    /// reducer.
    pub fn reduce(&mut self, reduce: bool) -> &mut Self {
        self.reduce = reduce;
        self
    }

    /// Restrict mutation to one or more named `MutationCategory` values.
    /// Pass an empty `Vec` (the default) to allow wasm-mutate's full
    /// built-in mutator pool, unrestricted, exactly as before this method
    /// existed.
    pub fn categories(&mut self, categories: Vec<MutationCategory>) -> &mut Self {
        self.categories = categories;
        self
    }

    /// Set a custom raw mutation function.
    ///
    /// This is used when we need some underlying raw bytes, for example when
    /// mutating the contents of a data segment.
    ///
    /// You can override this to use `libFuzzer`'s `LLVMFuzzerMutate` function
    /// to get raw bytes from `libFuzzer`, for example.
    ///
    /// The function is given the raw data buffer and the maximum size the
    /// mutated data should be. After mutating the data, the function should
    /// `resize` the data to its final, mutated size, which should be less than
    /// or equal to the maximum size.
    pub fn raw_mutate_func(
        &mut self,
        raw_mutate_func: Option<Arc<dyn Fn(&mut Vec<u8>, usize) -> Result<()>>>,
    ) -> &mut Self {
        self.raw_mutate_func = raw_mutate_func;
        self
    }

    pub(crate) fn consume_fuel(&mut self, qt: u64) -> Result<()> {
        if qt > self.fuel {
            log::info!("Out of fuel");
            return Err(Error::out_of_fuel());
        }
        self.fuel -= qt;
        Ok(())
    }

    /// Run this configured `WasmMutate` on the given input Wasm.
    pub fn run<'a>(
        &'a mut self,
        input_wasm: &'wasm [u8],
    ) -> Result<Box<dyn Iterator<Item = Result<Vec<u8>>> + 'a>> {
        self.setup(input_wasm)?;

        const MUTATORS: &[&dyn Mutator] = &[
            &PeepholeMutator::new(2),
            &RemoveExportMutator,
            &RenameExportMutator { max_name_size: 100 },
            &SnipMutator,
            &CodemotionMutator,
            &FunctionBodyUnreachable,
            &AddCustomSectionMutator,
            &ReorderCustomSectionMutator,
            &CustomSectionMutator,
            &AddTypeMutator {
                max_params: 20,
                max_results: 20,
            },
            &AddFunctionMutator,
            &RemoveSection::Custom,
            &RemoveSection::Empty,
            &ConstExpressionMutator::Global,
            &ConstExpressionMutator::ElementOffset,
            &ConstExpressionMutator::ElementFunc,
            &RemoveItemMutator(Item::Function),
            &RemoveItemMutator(Item::Global),
            &RemoveItemMutator(Item::Memory),
            &RemoveItemMutator(Item::Table),
            &RemoveItemMutator(Item::Type),
            &RemoveItemMutator(Item::Data),
            &RemoveItemMutator(Item::Element),
            &RemoveItemMutator(Item::Tag),
            &ModifyDataMutator {
                max_data_size: 10 << 20, // 10MB
            },
            &RemoveStartSection,
        ];

        // Attempt all mutators, but start at an arbitrary index.
        //
        // If `self.categories` was configured (non-empty), restrict the
        // candidate pool to just the mutators tagged with one of the
        // requested categories, built fresh here rather than reusing the
        // `MUTATORS` const above -- this list intentionally does NOT
        // include the original `CodemotionMutator` entry (it doesn't
        // correspond to a single named category on its own) and instead
        // uses the single-purpose `IfSwapMutator`/`LoopUnrollOnlyMutator`
        // for I6/I7. Several original mutators (RemoveExportMutator,
        // RenameExportMutator, ConstExpressionMutator variants,
        // ModifyDataMutator) don't map to any of the seven categories and
        // are therefore only reachable when `categories` is left empty.
        let categorized: Vec<(&dyn Mutator, MutationCategory)>;
        let peephole = PeepholeMutator::new(2);
        let add_type = AddTypeMutator { max_params: 20, max_results: 20 };
        let if_swap = IfSwapMutator;
        let loop_unroll = LoopUnrollOnlyMutator;
        let remove_items = [
            RemoveItemMutator(Item::Function),
            RemoveItemMutator(Item::Global),
            RemoveItemMutator(Item::Memory),
            RemoveItemMutator(Item::Table),
            RemoveItemMutator(Item::Type),
            RemoveItemMutator(Item::Data),
            RemoveItemMutator(Item::Element),
            RemoveItemMutator(Item::Tag),
        ];
        let candidates: Vec<&dyn Mutator> = if self.categories.is_empty() {
            MUTATORS.to_vec()
        } else {
            categorized = vec![
                (&peephole as &dyn Mutator, MutationCategory::Peephole),
                (&add_type as &dyn Mutator, MutationCategory::AddType),
                (&AddFunctionMutator as &dyn Mutator, MutationCategory::AddFunction),
                (&AddCustomSectionMutator as &dyn Mutator, MutationCategory::EditCustomSections),
                (&ReorderCustomSectionMutator as &dyn Mutator, MutationCategory::EditCustomSections),
                (&CustomSectionMutator as &dyn Mutator, MutationCategory::EditCustomSections),
                (&remove_items[0] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[1] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[2] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[3] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[4] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[5] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[6] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&remove_items[7] as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&RemoveSection::Custom as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&RemoveSection::Empty as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&RemoveStartSection as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&SnipMutator as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&FunctionBodyUnreachable as &dyn Mutator, MutationCategory::DeadCodeRemoval),
                (&if_swap as &dyn Mutator, MutationCategory::ConditionalSwap),
                (&loop_unroll as &dyn Mutator, MutationCategory::LoopUnrolling),
            ];
            categorized
                .iter()
                .filter(|(_, cat)| self.categories.contains(cat))
                .map(|(m, _)| *m)
                .collect()
        };

        if candidates.is_empty() {
            return Err(Error::no_mutations_applicable());
        }

        let start = self.rng().random_range(0..candidates.len());
        for m in candidates.iter().cycle().skip(start).take(candidates.len()) {
            let can_mutate = m.can_mutate(self);
            log::trace!("Can `{}` mutate? {}", m.name(), can_mutate);
            if !can_mutate {
                continue;
            }
            log::debug!("attempting to mutate with `{}`", m.name());
            match m.mutate(self) {
                Ok(iter) => {
                    log::debug!("mutator `{}` succeeded", m.name());
                    return Ok(Box::new(iter.into_iter().map(|r| r.map(|m| m.finish()))));
                }
                Err(e) => {
                    log::debug!("mutator `{}` failed: {}", m.name(), e);
                    return Err(e);
                }
            }
        }

        Err(Error::no_mutations_applicable())
    }

    fn setup(&mut self, input_wasm: &'wasm [u8]) -> Result<()> {
        self.info = Some(ModuleInfo::new(input_wasm)?);
        self.rng = Some(SmallRng::seed_from_u64(self.seed));
        Ok(())
    }

    pub(crate) fn rng(&mut self) -> &mut SmallRng {
        self.rng.as_mut().unwrap()
    }

    pub(crate) fn info(&self) -> &ModuleInfo<'wasm> {
        self.info.as_ref().unwrap()
    }

    fn raw_mutate(&mut self, data: &mut Vec<u8>, max_size: usize) -> Result<()> {
        // If a raw mutation function is configured then that's prioritized.
        if let Some(mutate) = &self.raw_mutate_func {
            return mutate(data, max_size);
        }

        // If no raw mutation function is configured then we apply a naive
        // default heuristic. For now that heuristic is to simply replace a
        // subslice of data with a random slice of other data.
        //
        // First up start/end indices are picked.
        let a = self.rng().random_range(0..=data.len());
        let b = self.rng().random_range(0..=data.len());
        let start = a.min(b);
        let end = a.max(b);

        // Next a length of the replacement is chosen. Note that the replacement
        // is always smaller than the input if reduction is requested, otherwise
        // we choose some arbitrary length of bytes to insert.
        let max_size = if self.reduce || self.rng().random() {
            0
        } else {
            max_size
        };
        let len = self
            .rng()
            .random_range(0..=end - start + max_size.saturating_sub(data.len()));

        // With parameters chosen the `Vec::splice` method is used to replace
        // the data in the input.
        data.splice(start..end, self.rng().random_iter().take(len));

        Ok(())
    }
}

#[cfg(test)]
pub(crate) fn validate(bytes: &[u8]) {
    use wasmparser::WasmFeatures;

    let mut validator = wasmparser::Validator::new_with_features(
        WasmFeatures::default() | WasmFeatures::MEMORY64 | WasmFeatures::MULTI_MEMORY,
    );
    let err = match validator.validate_all(bytes) {
        Ok(_) => return,
        Err(e) => e,
    };
    drop(std::fs::write("test.wasm", &bytes));
    if let Ok(text) = wasmprinter::print_bytes(bytes) {
        drop(std::fs::write("test.wat", &text));
    }

    panic!("wasm failed to validate: {err} (written to test.wasm)");
}
