#!/usr/bin/env bash
# Run the Spark eval and gold-data jobs one after another, in the background-friendly way.
#
#   tools/spark_queue.sh                 run every step that is not done yet
#   tools/spark_queue.sh --list          show the steps and which are done
#   tools/spark_queue.sh --only bank_ai,gen_gold4     run just these (comma separated)
#   tools/spark_queue.sh --force         ignore the "done" markers and run again
#   tools/spark_queue.sh --dry-run       print what would run, run nothing, touch nothing
#   tools/spark_queue.sh --no-check      do not probe vLLM / Ollama first
#
# Steps, in order: gen_gold4 (Qwen), gen_personal (Qwen), bank_ai (Glimmer), then the extraction eval (Glimmer) on every
# evals/gold/ledger{2,3,4}/receipts folder that exists (ledger2 has none: its documents use another schema),
# then cis_read and property_docs (both Glimmer).
#
# Run it from a shell on the Spark, e.g. `nohup tools/spark_queue.sh >/dev/null 2>&1 &`; it logs to
# ~/spark/accnomos/jobs/spark_queue.log. Resumable: a finished step leaves a marker in <jobs>/state/ and is skipped next
# time; a failed step is logged and the queue carries on with the next one (exit status 1 at the end). The steps resume
# themselves too (gen_gold4 reuses its saved catalogue and receipts, gen_personal its saved names and households,
# bank_ai its results.jsonl). Everything runs under nice 19 and ionice idle, one job at a time, so the production
# runtime on this machine keeps priority for the CPU and the disk; the GPU is shared, see evals/README.md.
#
# This script never runs git, never installs anything and writes only under evals/ (gold and runs) and the jobs folder.
# Environment: SPARK_JOBS_DIR (default ~/spark/accnomos/jobs), SPARK_PYTHON (default .venv/bin/python in the repo, else
# python3), STEP_TIMEOUT (default 8h per step), QWEN_URL / OLLAMA_URL (health probes).
set -u -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOBS="${SPARK_JOBS_DIR:-$HOME/spark/accnomos/jobs}"
LOG="$JOBS/spark_queue.log"
STATE="$JOBS/state"
QWEN_URL="${QWEN_URL:-http://127.0.0.1:8000/v1/models}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434/api/tags}"
STEP_TIMEOUT="${STEP_TIMEOUT:-8h}"
BIZ="Bramblewood Joinery Ltd"

ONLY="" FORCE=0 DRY=0 CHECK=1 LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --only) ONLY="${2:-}"; shift ;;
    --force) FORCE=1 ;;
    --dry-run) DRY=1 ;;
    --no-check) CHECK=0 ;;
    --list) LIST=1 ;;
    -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

if [ -n "${SPARK_PYTHON:-}" ]; then PY="$SPARK_PYTHON"
elif [ -x "$REPO/.venv/bin/python" ]; then PY="$REPO/.venv/bin/python"
else PY="$(command -v python3 || echo python3)"; fi

# Politeness prefix: lowest CPU priority, idle I/O class (each only when the tool exists).
PREFIX=(nice -n 19)
command -v ionice >/dev/null 2>&1 && PREFIX+=(ionice -c3)
TIMEOUT=()
command -v timeout >/dev/null 2>&1 && TIMEOUT=(timeout --foreground "$STEP_TIMEOUT")

log() { # message... -> log file and stdout
  local line
  line="$(date -Is) $*"
  echo "$line"
  [ "$DRY" = 1 ] || echo "$line" >>"$LOG"
}

# name | working directory (relative to the repo) | health probe (qwen|ollama|none) | command... (fields separated by US)
SEP=$'\x1f'
STEPS=()
add_step() { local IFS="$SEP"; STEPS+=("$*"); }
add_step gen_gold4 . qwen "$PY" evals/gold/gen_gold4.py
add_step gen_personal . qwen "$PY" evals/gold/gen_personal.py
add_step bank_ai evals ollama "$PY" -m harness.bank_ai
for d in ledger2 ledger3 ledger4; do
  # run_extraction scores receipt-schema documents: only a receipts/ folder qualifies
  add_step "extraction_$d" evals ollama "$PY" -m harness.run_extraction --mode local --messy \
    --gold-dir "gold/$d/receipts" --business-name "$BIZ" --out "runs/extraction_$d"
done
add_step cis_read evals ollama "$PY" -m harness.cis_read
add_step property_docs evals ollama "$PY" -m harness.property_docs

wanted() { [ -z "$ONLY" ] && return 0; case ",$ONLY," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
done_marker() { echo "$STATE/$1.done"; }

if [ "$LIST" = 1 ]; then
  for s in "${STEPS[@]}"; do
    IFS="$SEP" read -r name _ <<<"$s"
    if [ -e "$(done_marker "$name")" ]; then echo "$name: done"; else echo "$name: pending"; fi
  done
  exit 0
fi

if [ "$DRY" = 0 ]; then
  mkdir -p "$JOBS" "$STATE" || { echo "cannot create $JOBS" >&2; exit 2; }
  # one queue at a time
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$JOBS/spark_queue.lock"
    flock -n 9 || { echo "another spark_queue.sh is already running (lock $JOBS/spark_queue.lock)" >&2; exit 3; }
  fi
fi

probe() { # kind -> 0 when the model server answers
  case "$1" in
    qwen) curl -sf --max-time 5 -o /dev/null "$QWEN_URL" ;;
    ollama) curl -sf --max-time 5 -o /dev/null "$OLLAMA_URL" ;;
    *) return 0 ;;
  esac
}

failed=0 ran=0
log "queue start: repo=$REPO python=$PY prefix='${PREFIX[*]}' timeout=$STEP_TIMEOUT dry=$DRY"
for s in "${STEPS[@]}"; do
  IFS="$SEP" read -r -a f <<<"$s"
  name="${f[0]}" dir="${f[1]}" kind="${f[2]}" cmd=("${f[@]:3}")
  wanted "$name" || continue
  if [ "$FORCE" = 0 ] && [ -e "$(done_marker "$name")" ]; then
    log "STEP $name: skipped, already done (--force to run again)"
    continue
  fi
  case "$name" in
    extraction_*)
      d="${name#extraction_}"
      if ! compgen -G "$REPO/evals/gold/$d/receipts/*.json" >/dev/null; then
        log "STEP $name: skipped, no evals/gold/$d/receipts/*.json (run_extraction scores receipt-schema gold only; ledger2's documents use another schema)"
        continue
      fi ;;
  esac
  if [ "$DRY" = 1 ]; then
    log "STEP $name: would run in $dir: ${PREFIX[*]} ${TIMEOUT[*]} ${cmd[*]}"
    continue
  fi
  if [ "$CHECK" = 1 ] && ! probe "$kind"; then
    log "STEP $name: skipped, the $kind server did not answer (run again when it is up; --no-check to try anyway)"
    failed=1
    continue
  fi
  log "STEP $name: start in $dir: ${cmd[*]}"
  t0=$SECONDS
  (cd "$REPO/$dir" && PYTHONUNBUFFERED=1 PYTHONUTF8=1 "${PREFIX[@]}" "${TIMEOUT[@]}" "${cmd[@]}") >>"$LOG" 2>&1
  rc=$?
  ran=$((ran + 1))
  if [ "$rc" -eq 0 ]; then
    date -Is >"$(done_marker "$name")"
    log "STEP $name: done in $((SECONDS - t0))s"
  else
    failed=1
    log "STEP $name: FAILED rc=$rc after $((SECONDS - t0))s (see the log above; the next run resumes it)"
  fi
done
log "queue end: ran $ran step(s), failed=$failed"
exit "$failed"
