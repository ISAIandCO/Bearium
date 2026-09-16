#!/usr/bin/env bash

set -Eeuo pipefail

: "${RUNNER_TEMP:?RUNNER_TEMP must point to the GitHub runner temporary directory}"

diagnostic_dir="${RFIREFOX_BOOTSTRAP_DIAGNOSTIC_DIR:-$RUNNER_TEMP/rfirefox-bootstrap}"
heartbeat_seconds="${RFIREFOX_BOOTSTRAP_HEARTBEAT_SECONDS:-60}"

if [[ ! "$heartbeat_seconds" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid RFIREFOX_BOOTSTRAP_HEARTBEAT_SECONDS: $heartbeat_seconds" >&2
  exit 2
fi

mkdir -p "$diagnostic_dir"
bootstrap_log="$diagnostic_dir/bootstrap.log"
summary_log="$diagnostic_dir/summary.txt"
start_epoch="$(date +%s)"
heartbeat_pid=""

# Capture the command, bootstrap output and heartbeats in one file while still
# streaming everything to the GitHub Actions web UI.
exec > >(tee -a "$bootstrap_log") 2>&1

elapsed_text() {
  local now elapsed
  now="$(date +%s)"
  elapsed="$((now - start_epoch))"
  printf '%02d:%02d:%02d' \
    "$((elapsed / 3600))" \
    "$(((elapsed % 3600) / 60))" \
    "$((elapsed % 60))"
}

print_process_snapshot() {
  echo "Top processes by resident memory:"
  # Report executable names, not full arguments: command lines may contain
  # credentials injected by an Actions runner.
  ps -eo pid,ppid,stat,etime,pcpu,pmem,rss,comm --sort=-rss | head -n 16 || true
  echo "Bootstrap-related processes:"
  ps -eo pid,ppid,stat,etime,pcpu,pmem,rss,comm |
    awk '$8 ~ /^(mach|python|python3|rustup|cargo|sdkmanager|gradle|java|curl|wget)$/' || true
}

write_summary() {
  local status="$1"
  {
    echo "Bootstrap exit status: $status"
    echo "Elapsed: $(elapsed_text)"
    echo "Finished: $(date --iso-8601=seconds)"
    echo
    df -h "$RUNNER_TEMP" || true
    echo
    free -h || true
    echo
    du -sh "$HOME/.mozbuild" "$HOME/.gradle" 2>/dev/null || true
    echo
    print_process_snapshot
  } > "$summary_log"
  cat "$summary_log"
}

cleanup() {
  local status="$?"
  trap - EXIT INT TERM
  if [[ -n "$heartbeat_pid" ]]; then
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true
  fi
  write_summary "$status"
  exit "$status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Starting Firefox Android bootstrap"
echo "Started: $(date --iso-8601=seconds)"
echo "Bootstrap-specific timeout: disabled"
echo "Heartbeat interval: ${heartbeat_seconds}s"
echo "Working directory: $PWD"
uname -a
df -h "$RUNNER_TEMP"
free -h

(
  heartbeat_count=0
  while sleep "$heartbeat_seconds"; do
    heartbeat_count="$((heartbeat_count + 1))"
    echo
    echo "::notice title=Firefox bootstrap heartbeat::Elapsed $(elapsed_text); bootstrap is still running"
    date --iso-8601=seconds
    df -h "$RUNNER_TEMP" | tail -n 1 || true
    free -h | sed -n '1,2p' || true
    print_process_snapshot
    if ((heartbeat_count % 5 == 0)); then
      echo "Toolchain and Gradle cache sizes:"
      du -sh "$HOME/.mozbuild" "$HOME/.gradle" 2>/dev/null || true
    fi
  done
) &
heartbeat_pid="$!"

# MOZCONFIG is exported for the later build steps, but Firefox bootstrap must
# not see a path that does not exist yet. Let bootstrap create its conventional
# $PWD/mozconfig file, which is the path exported by the workflow.
unset MOZCONFIG ANDROID_HOME ANDROID_SDK_ROOT
# Bootstrap probes the host's default Android target, independently of our ABI.
# Install the ABI-specific ONNX from the official release graph afterwards;
# prepare_onnx_runtime.py makes it mandatory in the actual build's mozconfig.
set +e
PYTHONUNBUFFERED=1 stdbuf -oL -eL \
  ./mach --no-interactive bootstrap \
    --application-choice="GeckoView/Firefox for Android" \
    --exclude onnxruntime-x86_64-linux-android
bootstrap_status="$?"
set -e

if [[ "$bootstrap_status" -ne 0 ]]; then
  echo "::error title=Firefox bootstrap failed::mach bootstrap exited with status $bootstrap_status; inspect the uploaded diagnostics artifact."
fi

exit "$bootstrap_status"
