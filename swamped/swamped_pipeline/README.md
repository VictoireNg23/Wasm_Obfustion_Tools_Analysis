# Pipeline d'évaluation SWAMPED (NDSS)

Pipeline autonome, dédié uniquement à SWAMPED (SKKU-SecLab/SWAMPED). Ne
dépend d'aucun autre projet d'obfuscation (WasMixer, WasmMutate).

## Vérifié contre le vrai code source

`swamped_cli.py` (fourni séparément, hors dépôt public) a été inspecté
directement. Confirmé :
- **Les 20 noms de stratégies dans `combos.py` correspondent exactement**
  au dictionnaire `STRATEGIES` réel de `swamped_cli.py`. `custom_section_insertion`
  et `proxy_function_insertion` (P10 et P14 du papier) sont explicitement
  marquées `"fn": None` — non implémentées, exclues à raison de la liste.
- `stack_op_insertion` applique les **6 variantes** (`stackOP_insertion_memory/numeric/bit/conversion1/conversion2/floating`)
  par défaut ; `mba_transformation` applique **à la fois** `xor_MBA_transformation`
  et `or_MBA_transformation` ; `offset_expansion` → `load_store_transformation` ;
  `constant_value_transformation` → `constant_global_variables`. Tout ça est
  géré en interne par `swamped_cli.py`, pas par ce pipeline.
- `swamped_cli.py` calcule sa propre racine de projet via
  `os.path.dirname(__file__)` — **il ne dépend ni de `cwd` ni de
  `PYTHONPATH`** pour résoudre ses imports internes. `--swamped-repo` est
  conservé comme filet de sécurité, pas parce qu'il est strictement requis.

## Dépendance manquante identifiée (cause du `swamped_failed:rc=1`)

`strategies/code_perturbation.py` fait `import matplotlib.pyplot as plt`
au chargement du module — **jamais utilisé dans le code, mais l'import
seul plante si `matplotlib` n'est pas installé**, ce qui casse toute la
chaîne d'import (`swamped_cli.py` → `strategies.code_perturbation`) avant
même d'atteindre la logique d'obfuscation. C'est exactement l'erreur que
vous aviez vue, tronquée à la ligne 25 de `swamped_cli.py`
(`from strategies import code_perturbation as cp`). **`matplotlib` est
maintenant dans `requirements.txt`** — installez-le dans le **même**
environnement Python que celui qui exécute `run_swamped.py` (le pipeline
invoque `swamped_cli.py` avec `sys.executable`, donc le même interpréteur).

## Fichiers

| Fichier | Rôle |
|---|---|
| `combos.py` | Génère les 200 combinaisons stratégie × ratio (20 × 10 par défaut) |
| `pipeline_core.py` | Découverte récursive, métriques `*_orig` (cache), schéma CSV (avec colonne `ratio`) |
| `metrics_worker.py` | Applique **une** combinaison stratégie/ratio, calcule les métriques côté perturbé |
| `run_swamped.py` | **Script maître** |
| `common.py`, `wasm_runtime.py`, `cfg_similarity.py`, `cfg_from_wat.py`, `deobfuscation_vulnerability.py`, `orig_metrics.py`, `browser_runner.js`, `ghidra_count_functions.py` | Modules génériques, identiques à ceux des pipelines WasMixer/WasmMutate |

## Installation

```bash
pip install -r requirements.txt --break-system-packages
# wasmtime/wasmer, WABT, Binaryen : voir install_native_tools.sh des autres pipelines (générique)
# Node + puppeteer : voir setup_node.sh
```

## Lancement

```bash
python3 run_swamped.py \
    --dataset  /chemin/vers/dataset \
    --outdir   /chemin/vers/sortie \
    --csv      /chemin/vers/resultats.csv \
    --swamped-cli  /chemin/vers/SWAMPED/cli/swamped_cli.py \
    --swamped-repo /chemin/vers/SWAMPED \
    --browser-runner /chemin/vers/browser_runner.js \
    --node-path /tmp/puppeteer_env/node_modules \
    --wabt-bin /usr/bin \
    --wasmer-bin /root/.wasmer/bin/wasmer \
    --tmp-root /tmp/swamped_scratch \
    --cores $(nproc) \
    --timeout 60 \
    [--run-ghidra --ghidra-headless /opt/ghidra/support/analyzeHeadless]
```

**`--swamped-repo`** est important et spécifique à SWAMPED : votre script
d'origine lançait `swamped_cli.py` avec `export PYTHONPATH=$PYTHONPATH:.`
en étant positionné dans la racine du dépôt SWAMPED (pour que
`import strategies.code_perturbation` fonctionne). Ce pipeline reproduit
ça en fixant `cwd` et `PYTHONPATH` sur `--swamped-repo` à chaque appel —
sans ce flag pointé au bon endroit, `swamped_cli.py` échouera avec
`ModuleNotFoundError`.

## Combinaisons

**200 par échantillon par défaut** : 20 stratégies × 10 ratios (0.1 à 1.0,
pas de 0.1 — reprend la plage utilisée dans le papier SWAMPED, Section
IV-A). Restreignez avec `--strategies` / `--ratios` (listes séparées par
virgules) si vous voulez un sous-ensemble pour un premier test.

## payload_preserved

Le papier SWAMPED affirme que **toutes** ses perturbations préservent la
sémantique par construction (Section III-B). Contrairement à WasMixer
(où `T2`/chiffrement mémoire casse légitimement la comparaison brute) ou
WasmMutate (fuzzer, casse le comportement par design sans
`--preserve-semantics`), un `payload_preserved=no` ici est donc un signal
de correction plus direct — pas un compromis attendu. Si vous en voyez
beaucoup, ça vaut la peine d'investiguer (bug dans la stratégie, ou
`swamped_cli.py` qui ne fait pas ce qu'on pense — voir l'avertissement en
tête de ce README).
