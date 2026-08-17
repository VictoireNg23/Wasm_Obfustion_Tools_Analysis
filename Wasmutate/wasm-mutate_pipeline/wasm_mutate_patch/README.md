# Patch wasm-mutate : vraie sélection par catégorie (I1-I7)

## Pourquoi ce patch existe

`wasm-mutate` (bytecodealliance/wasm-tools) n'expose, ni via sa CLI
(`wasm-tools mutate`) ni via son API publique, aucun moyen de sélectionner
un mutateur précis : `run()` choisit toujours pseudo-aléatoirement parmi
son pool interne complet (~26 mutateurs). C'est pour ça que
`wasm_mutator_by_category` (votre wrapper) ne pouvait pas honorer
`--categories` malgré son nom — le concept n'existait nulle part en
dessous.

Ce patch ajoute, dans `wasm-mutate` lui-même :
- un enum public `MutationCategory` (I1-I7, une variante par catégorie de
  votre tableau NDSS),
- un champ `categories: Vec<MutationCategory>` sur `WasmMutate` (+ méthode
  `.categories(...)` et flag CLI `--categories` correspondant),
- un filtre dans `run()` qui restreint le pool de mutateurs candidats aux
  catégories demandées (si `categories` est vide, comportement **strictement
  identique** à avant le patch — rien n'est changé par défaut),
- deux nouveaux mutateurs `IfSwapMutator` / `LoopUnrollOnlyMutator` dans
  `codemotion.rs`, qui isolent I6 (conditional swap) et I7 (loop
  unrolling) — ces deux-là étaient encore imbriqués un niveau plus profond
  dans `CodemotionMutator`, qui choisissait aussi aléatoirement entre eux.

## Mapping I1-I7 -> mutateurs internes -> valeur `--categories`

| # | Nom (papier) | Valeur CLI | Mutateur(s) internes regroupés |
|---|---|---|---|
| I1 | Add type | `add-type` | `AddTypeMutator` |
| I2 | Add function | `add-function` | `AddFunctionMutator` |
| I3 | Edit custom sections | `edit-custom-sections` | `AddCustomSectionMutator`, `ReorderCustomSectionMutator`, `CustomSectionMutator` |
| I4 | Peephole rewriting | `peephole` | `PeepholeMutator` |
| I5 | Dead-code removal | `dead-code-removal` | `RemoveItemMutator` (Function/Global/Memory/Table/Type/Data/Element/Tag), `RemoveSection::{Custom,Empty}`, `RemoveStartSection`, `SnipMutator`, `FunctionBodyUnreachable` |
| I6 | Conditional swap | `conditional-swap` | `IfSwapMutator` (nouveau, isole `IfComplementMutator`) |
| I7 | Loop unrolling | `loop-unrolling` | `LoopUnrollOnlyMutator` (nouveau, isole `LoopUnrollMutator`) |

**Note honnête** : `RemoveExportMutator`, `RenameExportMutator`, les
variantes de `ConstExpressionMutator`, et `ModifyDataMutator` ne
correspondent à aucune des 7 catégories du papier — ils restent
accessibles uniquement en mode non filtré (`categories` vide). Si vous
voulez les inclure dans une catégorie existante ou en créer une nouvelle,
dites-le-moi.

## Limite importante : je n'ai pas pu compiler ce patch de bout en bout

Le bac à sable où j'ai travaillé plafonne à `rustc 1.75` (dépôt Ubuntu),
alors que le workspace `wasm-tools` actuel exige `rustc >= 1.85` (edition
2024). J'ai donc :
- vérifié la logique à la main, ligne par ligne, en m'appuyant sur des
  patterns déjà présents et fonctionnels dans le fichier original (mêmes
  types de littéraux de struct unitaires déjà utilisés dans le tableau
  `MUTATORS` d'origine),
- validé la syntaxe avec `rustfmt` (aucune erreur de parsing détectée),
- **mais je n'ai pas de `cargo build` vert à vous montrer.**

**Vous devez compiler et tester ce patch chez vous avant de vous en
servir pour de vraies données.** Votre environnement a déjà un toolchain
suffisant (votre bash script utilise `wasm-tools` avec succès).

## Comment appliquer, compiler, tester

```bash
git clone https://github.com/bytecodealliance/wasm-tools.git
cd wasm-tools

# remplacer les deux fichiers par les versions patchées
cp /chemin/vers/wasm_mutate_patch/lib.rs crates/wasm-mutate/src/lib.rs
cp /chemin/vers/wasm_mutate_patch/codemotion.rs crates/wasm-mutate/src/mutators/codemotion.rs

# compiler la CLI (feature "mutate" + "clap" doivent être actives -- normalement le cas par défaut du binaire wasm-tools)
cargo build --release --bin wasm-tools

# --- tests de non-régression : le mode SANS filtre doit rester identique ---
cargo test -p wasm-mutate

# --- test fonctionnel du nouveau filtre ---
echo '(module (func (export "f") (result i32) i32.const 1))' | \
  ./target/release/wasm-tools parse - -o /tmp/t.wasm

# doit marcher et ne produire QUE des mutations "add-type"
./target/release/wasm-tools mutate /tmp/t.wasm --seed 1 --categories add-type -o /tmp/out1.wasm
./target/release/wasm-tools mutate /tmp/t.wasm --seed 2 --categories add-type -o /tmp/out2.wasm

# doit échouer proprement sur un nom de catégorie invalide (pas un no-op silencieux)
./target/release/wasm-tools mutate /tmp/t.wasm --seed 1 --categories bogus-name -o /tmp/out3.wasm

# --- comparer visuellement plusieurs runs --categories peephole vs --categories add-type ---
# sur un binaire un peu plus riche que le module jouet ci-dessus, pour confirmer
# que chaque catégorie produit VRAIMENT des mutations de nature différente
# (ex: `wasm-tools print` avant/après pour repérer le type de changement)
```

Si `cargo test -p wasm-mutate` échoue à cause du patch (et pas d'un souci
d'environnement chez vous), montrez-moi l'erreur exacte et je corrige.

## Ensuite : recompiler le wrapper

```bash
cd wasm_mutator_by_category_src
cargo build --release
# copier le binaire là où votre pipeline Python l'attend (--mutator)
```

Le wrapper valide déjà les noms de catégories en amont (erreur explicite
si mal orthographié) et transmet `--categories` tel quel au `wasm-tools`
que vous venez de recompiler avec ce patch.
