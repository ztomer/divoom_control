#!/usr/bin/env bash
# Stop the helpers this app registered, BY THEIR IDENTITY.
#
# The helpers (`divoomd`, `divoom-menubar`) are bare binaries in their own
# sessions: a `quit:` by bundle id cannot reach them, and the only way to stop
# them used to be a NAME PATTERN (`pkill -f divoom-menubar`, and the homebrew
# cask's `pkill -f Divoom.app/Contents/Frameworks/bin/divoom`). A pattern is
# not an address — it reaches every process whose command line looks like the
# helper's, including ones this app does not own.
#
# The app writes an identity file per helper it spawns:
#
#     ~/.config/divoom-control/run/divoomd.pid
#     ~/.config/divoom-control/run/divoom-menubar.pid
#
# each naming ONE process: its pid, and the moment it started. The start time
# is what makes a stale identity safe — the OS reuses pids, so an identity
# left behind by a crashed run would otherwise point at whatever process took
# that pid next. This script compares the recorded start time with the live
# process's and leaves the process alone when they differ.
#
# Identity files exist only for helpers a build new enough to write them
# spawned. A helper from an older build (the one an upgrade replaces) has none,
# so a second pass stops whatever HOLDS the app's own endpoints -- the GUI's
# single-instance lock and the daemon's sockets -- resolved to pids with `lsof`.
# The holder of a socket path or a lock file is the process that owns it; that
# is an address too, not a name pattern.
#
# This is the shell half of `divoom_client/helper_identity.py`, for the
# callers that cannot run Python (an uninstall script, an installer). Both
# read the same files and apply the same rule.
set -euo pipefail

GOH="${GOH_DIR:-$HOME/Projects/gates_of_heck}"
# shellcheck disable=SC1091
[ -f "$GOH/tui/lib.sh" ] && source "$GOH/tui/lib.sh"
type info >/dev/null 2>&1 || { info() { echo "→ $*"; }; ok() { echo "✓ $*"; }
                               warn() { echo "⚠ $*"; }; err() { echo "✗ $*" >&2; }; }

RUN_DIR="${DIVOOM_IDENTITY_DIR:-$HOME/.config/divoom-control/run}"
# The endpoints the app owns: the GUI lock (a flock held for the GUI's life; the
# GUI respawns the daemon, so it goes first) and the daemon's sockets. The
# lock lives in the temp dir (`tempfile.gettempdir()` in single_instance.py).
GUI_LOCK="${DIVOOM_GUI_LOCK:-${TMPDIR:-/tmp}/divoom_gui.lock}"
DAEMON_SOCKETS="${DIVOOM_DAEMON_SOCKETS:-/tmp/divoom.sock:/tmp/divoomd.sock}"

stopped=0

# Stop every process holding one of the given paths: TERM, a short wait, then
# KILL for exactly the pids still holding it. Never this script or its parent.
stop_holders() {
    local label="$1" paths="$2" path pids pid left n=0
    local -a list
    IFS=: read -r -a list <<<"$paths"
    pids=""
    for path in "${list[@]}"; do
        [ -e "$path" ] || continue
        for pid in $(lsof -t "$path" 2>/dev/null || true); do
            if [ "$pid" != "$$" ] && [ "$pid" != "$PPID" ]; then
                pids="$pids $pid"
            fi
        done
    done
    [ -n "${pids// /}" ] || return 0
    for pid in $pids; do
        if kill "$pid" 2>/dev/null; then
            info "[helpers] $label: stopped pid $pid (holds its endpoint)"
            n=$((n + 1))
        fi
    done
    sleep 1
    for path in "${list[@]}"; do
        [ -e "$path" ] || continue
        left=$(lsof -t "$path" 2>/dev/null || true)
        for pid in $left; do
            case " $pids " in *" $pid "*) kill -9 "$pid" 2>/dev/null || true ;; esac
        done
    done
    stopped=$((stopped + n))
}

stop_holders "gui" "$GUI_LOCK"

for identity in "$RUN_DIR"/*.pid; do
    [ -f "$identity" ] || continue
    # One field per line, so one substitution each — no pipeline, and no
    # `head`: a consumer that exits early would SIGPIPE its producer.
    pid=$(sed -n 's/.*"pid"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$identity")
    started=$(sed -n 's/.*"started"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$identity")
    if [ -z "$pid" ] || [ -z "$started" ]; then
        warn "[helpers] $identity names no process — removing it"
        rm -f "$identity"
        continue
    fi
    # `ps` pads the column, so both ends are trimmed: the recorded value was
    # trimmed the same way when it was written.
    live=$(LC_ALL=C /bin/ps -p "$pid" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
    if [ -z "$live" ]; then
        info "[helpers] $(basename "$identity"): pid $pid is gone — removing the identity"
        rm -f "$identity"
        continue
    fi
    if [ "$live" != "$started" ]; then
        # The pid was reused: this is NOT the helper this identity named.
        warn "[helpers] $(basename "$identity"): pid $pid is a different process — leaving it alone"
        rm -f "$identity"
        continue
    fi
    if kill "$pid" 2>/dev/null; then
        info "[helpers] $(basename "$identity"): stopped pid $pid"
        stopped=$((stopped + 1))
    else
        warn "[helpers] $(basename "$identity"): could not stop pid $pid"
    fi
    rm -f "$identity"
done

stop_holders "daemon" "$DAEMON_SOCKETS"

if [ "$stopped" -eq 0 ]; then
    info "[helpers] nothing to stop"
else
    ok "[helpers] stopped $stopped helper(s) by identity or by the endpoint they hold"
fi
