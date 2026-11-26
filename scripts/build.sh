#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
[[ $(uname -sm) == 'Linux x86_64' ]]
python=${PYTHON:-python3}
"$python" scripts/inputs.py
work=$(mktemp -d "$root/out/build.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
export JAVA_HOME="$root/out/jdk"
unset JDK_JAVA_OPTIONS JAVA_TOOL_OPTIONS _JAVA_OPTIONS CLASSPATH
"$JAVA_HOME/bin/java" -version
mkdir -p "$work/dist" "$root/out/dist"
compiler_inputs=$("$python" scripts/inputs.py --compiler-inputs)
mapfile -t compiler_paths <<< "$compiler_inputs"
cp -- "${compiler_paths[0]}" "$work/protoc"
chmod +x "$work/protoc"
"$work/protoc" --version

runtime_classpath=${compiler_paths[1]}
kotlin_classpath=${compiler_paths[2]}

versions=$("$python" scripts/package_r8.py versions)
for version in $versions; do
  printf 'Building R8 %s\n' "$version"
  cd "$work"
  mkdir -p "$version"/{source,classes,generated,tmp}
  cd "$version"
  source_archives=$("$python" "$root/scripts/inputs.py" --source-archives "$version")
  while IFS= read -r archive; do
    module=$(basename "$archive" .tar.gz)
    mkdir -p "source/$module"
    tar -xzf "$archive" -C "source/$module"
  done <<< "$source_archives"

  "$work/protoc" --proto_path=source/keepanno/proto --proto_path=source/keepradius/proto \
    --java_out=generated source/keepanno/proto/keepspec.proto source/keepradius/proto/*.proto
  java_roots=(source/*/java generated)
  java_source_roots=$(IFS=,; printf '%s' "${java_roots[*]}")
  find source -type f -name '*.kt' | LC_ALL=C sort > kotlin-sources.txt
  find source generated -type f -name '*.java' | LC_ALL=C sort > java-sources.txt
  wc -l kotlin-sources.txt java-sources.txt
  "$JAVA_HOME/bin/java" -Xmx6g -Djava.io.tmpdir="$PWD/tmp" -cp "$kotlin_classpath" \
    org.jetbrains.kotlin.cli.jvm.K2JVMCompiler -version -jvm-target 11 -no-stdlib -no-reflect \
    -classpath "$runtime_classpath" -Xjava-source-roots="$java_source_roots" -d classes @kotlin-sources.txt
  "$JAVA_HOME/bin/javac" -J-Xmx8g -J-Djava.io.tmpdir="$PWD/tmp" --release 11 -proc:none \
    -encoding UTF-8 -cp "classes:$runtime_classpath" -d classes @java-sources.txt
  "$python" "$root/scripts/package_r8.py" "$version" "$work/dist"
done

mv -- "$work/dist/"* "$root/out/dist/"
