"""Assemble the standalone CLI or the AGP-compatible R8 archive."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

from inputs import CACHE, JDK, Lock, load_lock


DATABASE = "resources/api_database.ser"
CLI = {
    "d8": "com.android.tools.r8.D8",
    "r8": "com.android.tools.r8.R8",
    "retrace": "com.android.tools.r8.retrace.Retrace",
}
KOTLIN_SERVICE = (
    "META-INF/services/kotlin.metadata.internal.extensions.MetadataExtensions"
)


def source_jar(version: str, lock: Lock) -> Path:
    path = Path(f"r8-{version}.jar")
    with (
        ZipFile(path, "w", ZIP_DEFLATED) as jar,
        ZipFile(CACHE / "data" / lock["data"]["filename"]) as upstream,
    ):
        data = upstream.read(DATABASE)
        if sha256(data).hexdigest() != lock["api_database_sha256"]:
            raise ValueError("The upstream API database changed")
        jar.writestr(DATABASE, data)
        jar.writestr("META-INF/aosstudio/r8/LICENSE", upstream.read("LICENSE"))
        for name in ("LICENSE", "LIBRARY-LICENSE"):
            jar.write(CACHE / version / name, f"META-INF/aosstudio/r8/{name}.upstream")
        for root in (Path("classes"), Path("source/main/resources")):
            for file in sorted(root.rglob("*")):
                if file.is_file():
                    jar.write(file, file.relative_to(root))
    return path


def standalone(version: str, source: Path, lock: Lock, dist: Path) -> None:
    package = Path(f"aosstudio-r8-{version}")
    runtime = package / "lib/r8-runtime"
    runtime.mkdir(parents=True)
    shutil.copyfile(source, package / "lib" / source.name)
    for group in ("runtime", "compile"):
        for entry in lock[group]:
            shutil.copyfile(
                CACHE / group / entry["filename"], runtime / entry["filename"]
            )
    bin_dir = package / "bin"
    bin_dir.mkdir()
    for name, classname in CLI.items():
        launcher = bin_dir / name
        launcher.write_text(
            "#!/bin/sh\nset -eu\n"
            'tools_dir=$(CDPATH="" cd -- "$(dirname -- "$0")/.." && pwd)\n'
            "java=${JAVA_HOME:+$JAVA_HOME/bin/}java\n"
            f'exec "$java" -cp "$tools_dir/lib/{source.name}:$tools_dir/lib/r8-runtime/*" '
            f'"{classname}" "$@"\n'
        )
        launcher.chmod(0o755)
    for name in ("LICENSE", "LIBRARY-LICENSE"):
        shutil.copyfile(CACHE / version / name, package / name)
    (package / "inputs.json").write_text(
        json.dumps(
            {
                "r8_commit": lock["profiles"][version]["commit"],
                "api_database": lock["data"],
                "runtime": lock["runtime"] + lock["compile"],
            },
            indent=2,
        )
        + "\n"
    )
    subprocess.run(
        ["tar", "-czf", dist / f"{package.name}.tar.gz", package], check=True
    )


def relocate(version: str, source: Path, lock: Lock, dist: Path) -> None:
    deps = Path("deps.jar")
    entries: set[str] = set()
    with ZipFile(deps, "w", ZIP_DEFLATED) as jar:
        for entry in lock["runtime"]:
            with ZipFile(CACHE / "runtime" / entry["filename"]) as library:
                for name in sorted(library.namelist()):
                    if name in entries or name.startswith(
                        ("META-INF/versions/", "javax/annotation/", "wireless/")
                    ):
                        continue
                    if name.endswith("module-info.class"):
                        continue
                    if name.endswith(".class") or name == KOTLIN_SERVICE:
                        jar.writestr(name, library.read(name))
                        entries.add(name)

    build_rules = (CACHE / version / "build.gradle.kts").read_text()
    match = re.search(r"fun relocateDepsExceptAsm.*?\n}", build_rules, re.S)
    if match is None:
        raise ValueError("Missing upstream relocation rules")
    package = "com.android.tools.r8"
    rules = [
        f"{package}.**->{package}",
        f"{package}.keepanno.annotations.**->{package}.keepanno.annotations",
        f"{package}.keepanno.**->{package}.relocated.keepanno",
        f"org.objectweb.asm.**->{package}.org.objectweb.asm",
        *(
            rule.replace("${pkg}", package)
            for rule in re.findall(r'"([^"]+->[^"]+)"', match[0])
        ),
    ]
    classpath = os.pathsep.join(
        [
            str(source),
            *(str(CACHE / "runtime" / entry["filename"]) for entry in lock["runtime"]),
        ]
    )
    target = dist / f"aosstudio-r8-{version}-agp.jar"
    subprocess.run(
        [
            str(JDK / "bin/java"),
            "-Xmx6g",
            "-Djava.io.tmpdir=tmp",
            "-cp",
            classpath,
            "com.android.tools.r8.relocator.RelocatorCommandLine",
            "--input",
            str(source),
            "--input",
            str(deps),
            "--output",
            str(target),
            *(argument for rule in rules for argument in ("--map", rule)),
        ],
        check=True,
    )


def main() -> None:
    lock = load_lock()
    if sys.argv[1:] == ["versions"]:
        print(*lock["profiles"])
        return
    if sys.argv[1] == "verify":
        with ZipFile(sys.argv[2]) as jar:
            if sha256(jar.read(DATABASE)).hexdigest() != lock["api_database_sha256"]:
                raise ValueError("The packaged API database changed")
            jar.getinfo("META-INF/aosstudio/r8/LICENSE")
            if Path(jar.filename or "").name.endswith("-agp.jar"):
                jar.getinfo(
                    "com/android/tools/r8/com/google/common/collect/ImmutableList.class"
                )
                jar.getinfo("com/android/tools/r8/org/objectweb/asm/ClassReader.class")
        return
    version, output = sys.argv[1:]
    dist = Path(output)
    source = source_jar(version, lock)
    if "build.gradle.kts" in lock["profiles"][version]["files"]:
        relocate(version, source, lock, dist)
    else:
        standalone(version, source, lock, dist)


if __name__ == "__main__":
    main()
