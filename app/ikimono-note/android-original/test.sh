#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
JDK="${IKIMONO_ANDROID_JDK:-$HOME/.local/share/ikimono-android/jdk-21.0.12.1+1}"
mkdir -p build/test
"$JDK/bin/javac" --release 8 -encoding UTF-8 -d build/test src/jp/ikimononote/original/PhotoZip.java test/PhotoZipTest.java
"$JDK/bin/java" -cp build/test PhotoZipTest "$1" "${2:-/tmp/ikimono-android-original.zip}"
