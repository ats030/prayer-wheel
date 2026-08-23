#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TEST_HOME=$(mktemp -d /tmp/agent-context-test.XXXXXX)
trap 'rm -rf -- "$TEST_HOME"' EXIT HUP INT TERM

mkdir -p "$TEST_HOME/.claude" "$TEST_HOME/.config/opencode"
printf '# Test instructions\n' >"$TEST_HOME/AGENTS.md"
printf '{"model":"test/model"}\n' >"$TEST_HOME/.config/opencode/opencode.json"

python3 "$SCRIPT_DIR/agent_context.py" sync --home "$TEST_HOME"
python3 "$SCRIPT_DIR/agent_context.py" check --home "$TEST_HOME"

printf '# drift\n' >>"$TEST_HOME/.claude/CLAUDE.md"
if python3 "$SCRIPT_DIR/agent_context.py" check --home "$TEST_HOME" >/dev/null 2>&1; then
    echo "check unexpectedly accepted a drifted Claude adapter" >&2
    exit 1
fi

python3 "$SCRIPT_DIR/agent_context.py" sync --home "$TEST_HOME" >/dev/null
python3 "$SCRIPT_DIR/agent_context.py" check --home "$TEST_HOME" >/dev/null
grep -F '"model": "test/model"' "$TEST_HOME/.config/opencode/opencode.json" >/dev/null

echo "agent context synchronization tests passed"
