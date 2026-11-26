#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
python=${PYTHON:-python3}
export JAVA_HOME="$root/out/jdk"
unset JDK_JAVA_OPTIONS JAVA_TOOL_OPTIONS _JAVA_OPTIONS CLASSPATH
work=$(mktemp -d "$root/out/verify.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
"$JAVA_HOME/bin/java" -version
mkdir "$work/classes"
"$JAVA_HOME/bin/javac" --release 11 -d "$work/classes" tests/R8Smoke.java
"$JAVA_HOME/bin/jar" --create --file "$work/input.jar" -C "$work/classes" .

run_tool() {
  local tool=$1
  shift
  if [[ -n "$cli" ]]; then
    "$cli/bin/$tool" "$@"
    return
  fi
  local main
  case "$tool" in
    d8) main=com.android.tools.r8.D8 ;;
    r8) main=com.android.tools.r8.R8 ;;
    retrace) main=com.android.tools.r8.retrace.Retrace ;;
  esac
  "$JAVA_HOME/bin/java" -cp "$jar" "$main" "$@"
}

versions=$("$python" scripts/package_r8.py versions)
for version in $versions; do
  cd "$work"
  mkdir "$version"
  cd "$version"
  cli=
  jar="$root/out/dist/aosstudio-r8-$version-agp.jar"
  if [[ -f "$root/out/dist/aosstudio-r8-$version.tar.gz" ]]; then
    tar -xzf "$root/out/dist/aosstudio-r8-$version.tar.gz"
    cli="$PWD/aosstudio-r8-$version"
    jar="$cli/lib/r8-$version.jar"
  fi
  "$python" "$root/scripts/package_r8.py" verify "$jar"

  for tool in d8 r8 retrace; do
    run_tool "$tool" --version | grep -F " $version "
  done

  mkdir d8 dex
  run_tool d8 --min-api 21 --output d8 "$work/input.jar"
  [[ $(head -c 3 d8/classes.dex) == dex ]]

  run_tool r8 --classfile --release --lib "$JAVA_HOME" --output shrunk.jar \
    --pg-conf "$root/tests/keep.pro" --pg-map-output mapping.txt "$work/input.jar"
  "$JAVA_HOME/bin/jar" --list --file shrunk.jar > entries.txt
  grep -Fx R8Smoke.class entries.txt
  if grep -Fxq Unused.class entries.txt; then
    printf 'R8 kept an unused class\n' >&2
    exit 1
  fi
  [[ $("$JAVA_HOME/bin/java" -cp shrunk.jar R8Smoke) == 'R8 smoke test' ]]
  if "$JAVA_HOME/bin/java" -cp shrunk.jar R8Smoke crash 2> stacktrace.txt; then
    printf 'The fixture did not throw\n' >&2
    exit 1
  fi
  grep -E '^Crash -> [a-z]+:$' mapping.txt
  run_tool retrace mapping.txt stacktrace.txt > retraced.txt
  grep -F 'at Crash.raise(' retraced.txt
  grep -F 'at R8Smoke.main(' retraced.txt

  run_tool r8 --release --min-api 21 --lib "$JAVA_HOME" --output dex \
    --pg-conf "$root/tests/keep.pro" "$work/input.jar"
  [[ $(head -c 3 dex/classes.dex) == dex ]]
  printf 'R8 %s verified\n' "$version"
done
