#!/bin/sh
set -eu

ROOT=$(mktemp -d)
trap 'rm -rf "$ROOT"' EXIT
mkdir -p "$ROOT/bin" "$ROOT/home/app/sample/.git"

cat >"$ROOT/bin/git" <<'EOF'
#!/bin/sh
exit 0
EOF

cat >"$ROOT/bin/systemctl" <<'EOF'
#!/bin/sh
case "$*" in
  *"-p Description --value"*) echo "sample (port 9999)" ;;
  *) exit 0 ;;
esac
EOF

cat >"$ROOT/bin/curl" <<'EOF'
#!/bin/sh
out=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -w) shift 2 ;;
    *) shift ;;
  esac
done
printf '%s' "$FAKE_BODY" >"$out"
printf '200'
EOF

chmod +x "$ROOT/bin/git" "$ROOT/bin/systemctl" "$ROOT/bin/curl"
RUN="env HOME=$ROOT/home PATH=$ROOT/bin:/usr/bin:/bin"
DEPLOY="$(dirname "$0")/deploy.sh"
TAG='<script src="http://ubuntu-server-app:8526/v.js" data-site="sample" defer></script>'

FAKE_BODY="<!doctype html><html><head>$TAG</head></html>" \
    $RUN "$DEPLOY" sample >/dev/null

if FAKE_BODY='<!doctype html><html><head></head></html>' \
    $RUN "$DEPLOY" sample >/dev/null 2>&1; then
    echo "FAIL: タグなしHTMLを受理した" >&2
    exit 1
fi

FAKE_BODY='<!doctype html><html><head></head></html>' \
    VISIT_LOG_EXEMPT_REASON='CSP付き公開アプリ' \
    $RUN "$DEPLOY" sample >/dev/null

echo "OK: visit-log deploy gate"
