#!/usr/bin/env bash
f="$HOME/.beads/issues.jsonl"
git -C "$HOME" diff --quiet -- .beads/issues.jsonl && exit 0
if diff -q <(git -C "$HOME" show HEAD:.beads/issues.jsonl | sort) <(sort "$f") >/dev/null 2>&1; then
  git -C "$HOME" checkout -- .beads/issues.jsonl
  echo '{"suppressOutput":true}'
fi
