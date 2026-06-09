#!/usr/bin/env bash
#
# x-nuke launcher: set up the Python env, restart Brave with remote debugging
# enabled, attach via CDP, and run the wipe against your real X account.
#
# Usage:
#   ./nuke.sh                  # everything (tweets, likes, bookmarks, dms, lists)
#   ./nuke.sh tweets
#   ./nuke.sh likes
#   ./nuke.sh bookmarks
#   ./nuke.sh dms
#   ./nuke.sh lists
#
# Env vars:
#   CDP_PORT=9222              # change the debug port if 9222 is taken
#
set -euo pipefail

cd "$(dirname "$0")"

CATEGORY="${1:-all}"
CDP_PORT="${CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"

say() { printf '\033[1;36m[x-nuke]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[x-nuke]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x-nuke]\033[0m %s\n' "$*" >&2; exit 1; }

# 1. Detect Brave per-platform.
case "$(uname -s)" in
  Darwin)
    BRAVE_BIN="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    BRAVE_PROFILE="$HOME/Library/Application Support/BraveSoftware/Brave-Browser"
    ;;
  Linux)
    BRAVE_BIN="$(command -v brave-browser 2>/dev/null || command -v brave 2>/dev/null || true)"
    BRAVE_PROFILE="$HOME/.config/BraveSoftware/Brave-Browser"
    ;;
  *)
    die "Unsupported OS: $(uname -s). Supported: macOS, Linux."
    ;;
esac

if [ -z "${BRAVE_BIN}" ] || [ ! -e "${BRAVE_BIN}" ]; then
  die "Brave Browser not found. Install from https://brave.com/ then retry."
fi

# 2. Require Python 3.10+ (we use str | None syntax).
if ! command -v python3 >/dev/null; then
  die "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/."
fi
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')"
[ "${PY_OK}" = "1" ] || die "Python 3.10+ required (found ${PY_VER})."

# 3. Set up venv + deps (idempotent — only runs the slow steps on first launch).
if [ ! -d .venv ]; then
  say "First run: creating Python venv (.venv/)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import playwright" 2>/dev/null; then
  say "Installing Python deps..."
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
  say "Installing Playwright Chromium (one-time, used as a fallback browser)..."
  playwright install chromium >/dev/null
fi

# 4. Restart Brave with --remote-debugging-port so Playwright can attach to it.
if pgrep -f "Brave Browser" >/dev/null 2>&1; then
  warn "Brave is running. To enable remote debugging, it has to restart."
  warn "Save anything important, then press Enter to continue (Ctrl+C to abort)."
  read -r _
  pkill -9 -f "Brave Browser" 2>/dev/null || true
  sleep 2
fi

say "Launching Brave with remote debugging on port ${CDP_PORT}..."
"${BRAVE_BIN}" \
  --remote-debugging-port="${CDP_PORT}" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="${BRAVE_PROFILE}" \
  > /tmp/brave-cdp.log 2>&1 &

# 5. Wait for CDP to come up.
printf '\033[1;36m[x-nuke]\033[0m Waiting for Brave CDP'
for _ in $(seq 1 20); do
  sleep 1
  if curl -sf "${CDP_URL}/json/version" >/dev/null; then
    printf ' — ready.\n'
    break
  fi
  printf '.'
done
if ! curl -sf "${CDP_URL}/json/version" >/dev/null; then
  printf '\n'
  die "Brave CDP never came up. See /tmp/brave-cdp.log for details."
fi

# 6. Run the wipe. If you're not logged in to x.com, the Python tool will open the
#    login page in a Brave tab and wait up to 10 minutes for you to finish.

# In parallel mode, split tweets into two passes so each runs in its own tab/process.
CATEGORIES=(tweets-posts tweets-replies likes bookmarks dms lists)

run_one_sequential() {
  exec python wipe.py "$1" --yes-really-delete --force --cdp "${CDP_URL}"
}

run_all_parallel() {
  say "Starting all categories in parallel. Each runs in its own Brave tab"
  say "and closes itself when there's nothing left to delete."
  say "Note: Brave focus will jump between tabs — don't try to use it for anything else."

  pids=()
  trap 'echo; warn "Interrupted — killing child runs."; kill ${pids[@]} 2>/dev/null || true; exit 130' INT TERM

  for cat in "${CATEGORIES[@]}"; do
    # Prefix each line with [<category>] so interleaved output stays readable.
    (
      python wipe.py "$cat" --yes-really-delete --force --cdp "${CDP_URL}" 2>&1 \
        | sed -u "s/^/[${cat}] /"
    ) &
    pids+=($!)
    # Small stagger so the 5 Playwright connections don't race the initial login check.
    sleep 1
  done

  fail=0
  for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
      fail=$((fail + 1))
    fi
  done

  if [ "$fail" -eq 0 ]; then
    say "All categories finished cleanly."
  else
    warn "$fail of ${#pids[@]} categories exited non-zero. Check logs/ for details."
  fi
  exit "$fail"
}

if [ "${CATEGORY}" = "all" ]; then
  run_all_parallel
else
  say "Starting wipe: ${CATEGORY}"
  run_one_sequential "${CATEGORY}"
fi
