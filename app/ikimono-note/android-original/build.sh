#!/usr/bin/env bash
# No Gradle or runtime dependencies. SDK/JDK and release key stay outside the repository.
set -euo pipefail
cd "$(dirname "$0")"
JDK="${IKIMONO_ANDROID_JDK:-$HOME/.local/share/ikimono-android/jdk-21.0.12.1+1}"
SDK="${IKIMONO_ANDROID_SDK:-$HOME/.local/share/ikimono-android}"
TOOLS="${IKIMONO_ANDROID_TOOLS:-$SDK/android-15}"
PLATFORM="${IKIMONO_ANDROID_PLATFORM:-$SDK/android-35/android.jar}"
SIGNING="${IKIMONO_ANDROID_SIGNING:-$HOME/.local/share/ikimono-android/signing}"
export JAVA_HOME="$JDK"
export PATH="$JDK/bin:$PATH"
for program in javac java jar keytool; do command -v "$program" >/dev/null; done
test -f "$PLATFORM"
mkdir -p build/generated build/classes build/dex ../static/downloads
"$TOOLS/aapt2" compile --dir res -o build/resources.zip
"$TOOLS/aapt2" link -o build/base.apk -I "$PLATFORM" --manifest AndroidManifest.xml --java build/generated build/resources.zip
mapfile -t sources < <(find src build/generated -name '*.java' -type f)
javac --release 8 -encoding UTF-8 -classpath "$PLATFORM" -d build/classes "${sources[@]}"
jar cf build/classes.jar -C build/classes .
"$TOOLS/d8" --min-api 29 --lib "$PLATFORM" --output build/dex build/classes.jar
python3 - <<'PY'
from pathlib import Path
from zipfile import ZipFile
with ZipFile('build/base.apk') as source, ZipFile('build/unsigned.apk','w') as target:
    for item in source.infolist(): target.writestr(item, source.read(item.filename))
    target.write('build/dex/classes.dex', 'classes.dex')
PY
"$TOOLS/zipalign" -f 4 build/unsigned.apk build/aligned.apk
if [ ! -f "$SIGNING/release.jks" ] || [ ! -f "$SIGNING/password" ]; then
    printf '%s\n' "Release signing key is missing: $SIGNING. See README.md." >&2
    exit 1
fi
"$TOOLS/apksigner" sign --v4-signing-enabled false --ks "$SIGNING/release.jks" --ks-pass "file:$SIGNING/password" --out ../static/downloads/ikimono-original-0.1.0.apk build/aligned.apk
"$TOOLS/apksigner" verify --verbose --print-certs ../static/downloads/ikimono-original-0.1.0.apk
sha256sum ../static/downloads/ikimono-original-0.1.0.apk
