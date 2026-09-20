#!/bin/bash
set -eu

SESSION_NAME="${OPENCODE_SESSION_NAME:-opencode}"
REAL_OPENCODE="${OPENCODE_REAL:-$HOME/.opencode/bin/opencode}"
STATUS_SCRIPT="${OPENCODE_STATUS_SCRIPT:-$HOME/scripts/opencode-tmux-status.py}"
TMUX_BIN="${OPENCODE_TMUX:-tmux}"
STATUS_COMMAND="#(python3 $STATUS_SCRIPT)"

configure_status() {
  target=$1
  "$TMUX_BIN" set-option -t "$target" status on
  "$TMUX_BIN" set-option -t "$target" status-interval 1
  "$TMUX_BIN" set-option -t "$target" status-right-length 100
  "$TMUX_BIN" set-option -t "$target" status-right "$STATUS_COMMAND"
}

if [ -n "${TMUX:-}" ]; then
  current_session=$("$TMUX_BIN" display-message -p '#S')
  configure_status "$current_session"
  exec "$REAL_OPENCODE" "$@"
fi

if "$TMUX_BIN" has-session -t "=$SESSION_NAME" 2>/dev/null; then
  exec "$TMUX_BIN" attach-session -t "=$SESSION_NAME"
fi

"$TMUX_BIN" new-session -d -s "$SESSION_NAME" -c "$PWD" "$REAL_OPENCODE" "$@"
configure_status "$SESSION_NAME"
exec "$TMUX_BIN" attach-session -t "=$SESSION_NAME"
