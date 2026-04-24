#!/bin/bash
set -u
set -o pipefail

# ==========================================================
# CONFIG
# ==========================================================
BASE_DIR="./Dataset_officiel_wasm"

ORIG_WASM_DIR="$BASE_DIR/GillianC"
MUT_WASM_DIR="./Wasmutate/WasmMutate_Results_wasmer/GillianC"
RESULTS_DIR="$MUT_WASM_DIR/Results_GillianC_wasmer"
CSV_FILE="./WasmMutate_Results/Results_Csv/Results_Spectec_Wasmutate_Wasmer/GillianC.csv"
LOG_FILE="$MUT_WASM_DIR/Log_wasmer/GillianC.log"

MUTATOR="./Wasmutate/wasm_mutator_by_category/target/release/wasm_mutator_by_category"
NODE_PUPPET="./Wasmutate/run_browser_test.js"

# === WASM Runtime ===
WASM_RUNTIME="wasmer"
TIMEOUT_SEC=300   

mkdir -p "$MUT_WASM_DIR" "$RESULTS_DIR" "$(dirname "$CSV_FILE")"
: > "$LOG_FILE"

# ==========================================================
# TRANSFORMATIONS
# ==========================================================
TRANSFORMATIONS=("peephole" "add_type" "add_function" "remove_dead_code" "edit_custom_sections" "if_swap" "loop_unroll")
NB_MUTANTS=3
TEST_INPUTS='[[1,2],[5,7],[10,20]]'

# ==========================================================
# CSV HEADER
# ==========================================================
echo "sample,relpath,obfuscation_transformation,mutant_id,size_orig,size_obf,call_ind_orig,call_ind_obf,max_nesting_orig,max_nesting_obf,obf_time,valid_orig,valid_obf,run_time_orig,run_orig,run_time_obf,run_obf,disassembly_ok_orig,disassembly_ok_obf,wat_similarity,cfg_similarity,func_symbols_orig,func_symbols_obf,type_symbols_orig,type_symbols_obf,orig_state_hash,obf_state_hash,state_match,behavior_match" > "$CSV_FILE"

# ==========================================================
# LOGGING
# ==========================================================
log() {
    echo "[$(date +'%F %T')] $*" | tee -a "$LOG_FILE"
}

# ==========================================================
# RUNTIME (Wasmer)
# ==========================================================
run_runtime_capture() {
    local file="$1"
    local outlog="$2"

    local start end status runtime
    start=$(date +%s%3N)

    timeout "$TIMEOUT_SEC" "$WASM_RUNTIME" "$file" > "$outlog" 2>&1
    status=$?

    end=$(date +%s%3N)
    runtime=$((end - start))

    if [[ $status -eq 124 ]]; then
        echo "$runtime,timeout"
    elif [[ $status -eq 0 || $status -eq 1 ]]; then
        echo "$runtime,ok"
    else
        echo "$runtime,fail"
    fi
}

# ==========================================================
# METRICS
# ==========================================================
validate_wasm() {
    wasm-tools validate "$1" >/dev/null 2>&1 && echo "yes" || echo "no"
}

count_call_indirect() {
    wasm-tools print "$1" 2>/dev/null | grep -c "call_indirect"
}

max_nesting_depth() {
    local wasm="$1"
    local wat
    wat=$(wasm2wat "$wasm" 2>/dev/null || true)
    [[ -z "$wat" ]] && echo 0 && return

    python3 - <<EOF
import re
d=0;m=0
for l in """$wat""".splitlines():
    for t in re.findall(r"[()]", l):
        if t=="(":
            d+=1;m=max(m,d)
        else:
            d=max(0,d-1)
print(m)
EOF
}

disassembly_ok() {
    wasm2wat "$1" >/dev/null 2>&1 && echo "yes" || echo "no"
}

wat_similarity() {
    local a="$1"; local b="$2"
    local d
    d=$(mktemp -d)

    wasm2wat "$a" -o "$d/a.wat" 2>/dev/null || { echo "ERROR"; rm -rf "$d"; return; }
    wasm2wat "$b" -o "$d/b.wat" 2>/dev/null || { echo "ERROR"; rm -rf "$d"; return; }

    python3 - <<EOF
from difflib import SequenceMatcher
a=open("$d/a.wat").read()
b=open("$d/b.wat").read()
print("{:.2f}".format(SequenceMatcher(None,a,b).ratio()*100))
EOF
    rm -rf "$d"
}

cfg_similarity() {
    local a="$1"; local b="$2"
    local d
    d=$(mktemp -d)

    wasm-opt --print-cfg "$a" 2>/dev/null | grep -- "->" > "$d/a" || true
    wasm-opt --print-cfg "$b" 2>/dev/null | grep -- "->" > "$d/b" || true

    python3 - <<EOF
A=set(open("$d/a").read().splitlines())
B=set(open("$d/b").read().splitlines())
print("{:.2f}".format((len(A&B)/len(A|B))*100 if A|B else 0))
EOF
    rm -rf "$d"
}

count_func_symbols() {
    wasm-objdump -x "$1" 2>/dev/null | grep "Export.*func" | wc -l
}

count_type_symbols() {
    wasm-objdump -x "$1" 2>/dev/null | grep "^Type" | wc -l
}

# ==========================================================
# COMBINATIONS
# ==========================================================
generate_all_combinations() {
    local -n arr=$1
    local n=${#arr[@]}

    for ((m=1; m<(1<<n); m++)); do
        c=()
        for ((i=0; i<n; i++)); do
            ((m>>i & 1)) && c+=("${arr[i]}")
        done
        IFS=_; echo "${c[*]}"
    done
}


ALL_COMBOS=($(generate_all_combinations TRANSFORMATIONS))
log "Total combinations: ${#ALL_COMBOS[@]}"

# ==========================================================
# PROCESS ONE FILE
# ==========================================================
process_wasm_file() {
    local wasm="$1"
    local sample
    sample=$(basename "$wasm")

    log "Processing $sample"

    size_orig=$(stat -c%s "$wasm")
    call_ind_orig=$(count_call_indirect "$wasm")
    max_nesting_orig=$(max_nesting_depth "$wasm")
    valid_orig=$(validate_wasm "$wasm")

    rt=$(run_runtime_capture "$wasm" "/tmp/orig.log")
    run_time_orig=${rt%%,*}
    run_orig=${rt##*,}

    orig_browser_dir="$RESULTS_DIR/$sample/original"
    mkdir -p "$orig_browser_dir"
    node "$NODE_PUPPET" --wasm "$wasm" --outdir "$orig_browser_dir" --inputs "$TEST_INPUTS" >/dev/null 2>&1
    orig_state_hash=$(sha256sum "$orig_browser_dir/browser_state.json" 2>/dev/null | awk '{print $1}')

    for combo in "${ALL_COMBOS[@]}"; do
        for ((i=1;i<=NB_MUTANTS;i++)); do
            outdir="$MUT_WASM_DIR/$sample/$combo/mut$i"
            mkdir -p "$outdir"

            obf_start=$(date +%s%3N)
            "$MUTATOR" --input "$wasm" --categories "$combo" --variants 1 --outdir "$outdir" >/dev/null 2>&1 || true
            obf_end=$(date +%s%3N)
            obf_time=$((obf_end - obf_start))

            mutant=$(find "$outdir" -name "*.wasm" | head -n1)
            [[ ! -f "$mutant" ]] && continue

            size_obf=$(stat -c%s "$mutant")
            call_ind_obf=$(count_call_indirect "$mutant")
            max_nesting_obf=$(max_nesting_depth "$mutant")
            valid_obf=$(validate_wasm "$mutant")

            rt2=$(run_runtime_capture "$mutant" "$outdir/run.log")
            run_time_obf=${rt2%%,*}
            run_obf=${rt2##*,}

            node "$NODE_PUPPET" --wasm "$mutant" --outdir "$outdir" --inputs "$TEST_INPUTS" >/dev/null 2>&1
            obf_state_hash=$(sha256sum "$outdir/browser_state.json" 2>/dev/null | awk '{print $1}')

            state_match=$([[ "$orig_state_hash" == "$obf_state_hash" ]] && echo yes || echo no)
            behavior_match=$([[ "$state_match" == yes && "$run_obf" == ok ]] && echo yes || echo no)

            printf "%s,%s,%s,mut%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,yes,yes,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
            "$sample" "$wasm" "$combo" "$i" \
            "$size_orig" "$size_obf" "$call_ind_orig" "$call_ind_obf" \
            "$max_nesting_orig" "$max_nesting_obf" \
            "$obf_time" \
            "$valid_orig" "$valid_obf" \
            "$run_time_orig" "$run_orig" \
            "$run_time_obf" "$run_obf" \
            "$(wat_similarity "$wasm" "$mutant")" "$(cfg_similarity "$wasm" "$mutant")" \
            "$(count_func_symbols "$wasm")" "$(count_func_symbols "$mutant")" \
            "$(count_type_symbols "$wasm")" "$(count_type_symbols "$mutant")" \
            "$orig_state_hash" "$obf_state_hash" "$state_match" "$behavior_match" >> "$CSV_FILE"

            log "OK $sample | $combo | mut$i | run_obf=$run_obf | obf_time=${obf_time}ms"
        done
    done
}

# ==========================================================
# MAIN
# ==========================================================
find "$ORIG_WASM_DIR" -name "*.wasm" | while read -r f; do
    process_wasm_file "$f"
done

log "ALL DONE"
