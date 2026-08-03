# CLAUDE.md の完了条件は「git push が成功するまで」。取り残しを機械で拾う。
pending=""
for repo in "$HOME" "$HOME"/app/*/; do
  [ -d "$repo/.git" ] || continue
  name=$(basename "$repo")
  [ "$repo" = "$HOME" ] && name="~"
  ahead=$(git -C "$repo" rev-list --count @{u}..HEAD 2>/dev/null) || continue
  dirty=$(git -C "$repo" status --porcelain 2>/dev/null | grep -cv '^??')
  [ "$ahead" -eq 0 ] && [ "$dirty" -eq 0 ] && continue
  pending="$pending $name(未push:${ahead} 未commit:${dirty})"
done
[ -z "$pending" ] && exit 0
printf '%s' "$pending" | python3 -c 'import sys,json; print(json.dumps({"systemMessage":"未完了の作業があります —"+sys.stdin.read()+"  (CLAUDE.md: git push まで完了ではありません)"}))'
