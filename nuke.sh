#!/usr/bin/env bash
#
# x-nuke launcher: set up the Python env, restart your Chromium-based browser
# with remote debugging enabled, attach via CDP, and run the wipe against your
# real X account.
#
# Usage:
#   ./nuke.sh                  # everything (6 categories in parallel)
#   ./nuke.sh tweets
#   ./nuke.sh tweets-posts
#   ./nuke.sh tweets-replies
#   ./nuke.sh likes
#   ./nuke.sh bookmarks
#   ./nuke.sh dms
#   ./nuke.sh lists
#
# Env vars:
#   BROWSER=brave|chrome|edge|chromium|arc|vivaldi   pick a specific browser
#   CDP_PORT=9222                                    change the debug port
#
set -euo pipefail

cd "$(dirname "$0")"

CATEGORY="${1:-all}"
CDP_PORT="${CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"

say()  { printf '\033[1;36m[x-nuke]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[x-nuke]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x-nuke]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- browser detection ---------------------------------------------------
# Per-browser facts: name, binary path, user-data-dir, pkill pattern.
# Populated by get_browser_info; success means the binary is also installed.

OS="$(uname -s)"

get_browser_info() {
  BROWSER_NAME=""; BROWSER_BIN=""; BROWSER_PROFILE=""; BROWSER_PKILL=""
  case "${OS}:$1" in
    Darwin:brave)
      BROWSER_NAME="Brave Browser"
      BROWSER_BIN="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
      BROWSER_PROFILE="$HOME/Library/Application Support/BraveSoftware/Brave-Browser"
      BROWSER_PKILL="Brave Browser"
      ;;
    Darwin:chrome)
      BROWSER_NAME="Google Chrome"
      BROWSER_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
      BROWSER_PROFILE="$HOME/Library/Application Support/Google/Chrome"
      BROWSER_PKILL="Google Chrome"
      ;;
    Darwin:edge)
      BROWSER_NAME="Microsoft Edge"
      BROWSER_BIN="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
      BROWSER_PROFILE="$HOME/Library/Application Support/Microsoft Edge"
      BROWSER_PKILL="Microsoft Edge"
      ;;
    Darwin:chromium)
      BROWSER_NAME="Chromium"
      BROWSER_BIN="/Applications/Chromium.app/Contents/MacOS/Chromium"
      BROWSER_PROFILE="$HOME/Library/Application Support/Chromium"
      BROWSER_PKILL="Chromium"
      ;;
    Darwin:arc)
      BROWSER_NAME="Arc"
      BROWSER_BIN="/Applications/Arc.app/Contents/MacOS/Arc"
      BROWSER_PROFILE="$HOME/Library/Application Support/Arc/User Data"
      BROWSER_PKILL="Arc"
      ;;
    Darwin:vivaldi)
      BROWSER_NAME="Vivaldi"
      BROWSER_BIN="/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"
      BROWSER_PROFILE="$HOME/Library/Application Support/Vivaldi"
      BROWSER_PKILL="Vivaldi"
      ;;
    Linux:brave)
      BROWSER_NAME="Brave Browser"
      BROWSER_BIN="$(command -v brave-browser 2>/dev/null || command -v brave 2>/dev/null || true)"
      BROWSER_PROFILE="$HOME/.config/BraveSoftware/Brave-Browser"
      BROWSER_PKILL="brave"
      ;;
    Linux:chrome)
      BROWSER_NAME="Google Chrome"
      BROWSER_BIN="$(command -v google-chrome 2>/dev/null || command -v google-chrome-stable 2>/dev/null || true)"
      BROWSER_PROFILE="$HOME/.config/google-chrome"
      BROWSER_PKILL="chrome"
      ;;
    Linux:edge)
      BROWSER_NAME="Microsoft Edge"
      BROWSER_BIN="$(command -v microsoft-edge 2>/dev/null || command -v microsoft-edge-stable 2>/dev/null || true)"
      BROWSER_PROFILE="$HOME/.config/microsoft-edge"
      BROWSER_PKILL="msedge"
      ;;
    Linux:chromium)
      BROWSER_NAME="Chromium"
      BROWSER_BIN="$(command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null || true)"
      BROWSER_PROFILE="$HOME/.config/chromium"
      BROWSER_PKILL="chromium"
      ;;
    Linux:vivaldi)
      BROWSER_NAME="Vivaldi"
      BROWSER_BIN="$(command -v vivaldi 2>/dev/null || command -v vivaldi-stable 2>/dev/null || true)"
      BROWSER_PROFILE="$HOME/.config/vivaldi"
      BROWSER_PKILL="vivaldi"
      ;;
    *)
      return 1
      ;;
  esac
  [ -n "${BROWSER_BIN}" ] && [ -e "${BROWSER_BIN}" ]
}

# Priority order when auto-detecting. BROWSER= env var overrides.
CANDIDATES=(brave chrome edge chromium arc vivaldi)

if [ -n "${BROWSER:-}" ]; then
  if ! get_browser_info "${BROWSER}"; then
    die "BROWSER=${BROWSER} is not installed (or not supported on ${OS})."
  fi
else
  found=0
  for cand in "${CANDIDATES[@]}"; do
    if get_browser_info "${cand}"; then
      found=1
      break
    fi
  done
  [ "${found}" = "1" ] || die "No supported browser found. Install one of: Brave, Chrome, Edge, Chromium, Arc (mac), Vivaldi."
fi

# ---- Python + deps --------------------------------------------------------

if ! command -v python3 >/dev/null; then
  die "python3 not found. Install Python 3.10+ from https://www.python.org/downloads/."
fi
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')"
[ "${PY_OK}" = "1" ] || die "Python 3.10+ required (found ${PY_VER})."

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

# ---- restart browser with CDP --------------------------------------------

if pgrep -f "${BROWSER_PKILL}" >/dev/null 2>&1; then
  warn "${BROWSER_NAME} is running. To enable remote debugging, it has to restart."
  warn "Save anything important, then press Enter to continue (Ctrl+C to abort)."
  read -r _
  pkill -9 -f "${BROWSER_PKILL}" 2>/dev/null || true
  sleep 2
fi

say "Launching ${BROWSER_NAME} with remote debugging on port ${CDP_PORT}..."
"${BROWSER_BIN}" \
  --remote-debugging-port="${CDP_PORT}" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="${BROWSER_PROFILE}" \
  > /tmp/x-nuke-browser.log 2>&1 &

printf '\033[1;36m[x-nuke]\033[0m Waiting for browser CDP'
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
  die "${BROWSER_NAME} CDP never came up. See /tmp/x-nuke-browser.log for details."
fi

# ---- run the wipe --------------------------------------------------------
#
# If you're not logged in to x.com, the Python tool will open the login page in
# a tab and wait up to 10 minutes for you to finish.

# In parallel mode, tweets is split into two passes so each runs in its own tab.
CATEGORIES=(tweets-posts tweets-replies likes bookmarks dms lists)

run_one_sequential() {
  exec python wipe.py "$1" --yes-really-delete --force --cdp "${CDP_URL}"
}

run_all_parallel() {
  say "Starting all categories in parallel. Each runs in its own ${BROWSER_NAME} tab"
  say "and closes itself when there's nothing left to delete."
  say "Note: ${BROWSER_NAME} focus will jump between tabs — don't try to use it for anything else."

  pids=()
  trap 'echo; warn "Interrupted — killing child runs."; kill ${pids[@]} 2>/dev/null || true; exit 130' INT TERM

  for cat in "${CATEGORIES[@]}"; do
    (
      python wipe.py "$cat" --yes-really-delete --force --cdp "${CDP_URL}" 2>&1 \
        | sed -u "s/^/[${cat}] /"
    ) &
    pids+=($!)
    # Small stagger so the Playwright connections don't race the initial login check.
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
