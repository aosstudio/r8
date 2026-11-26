"""Fetch and verify the inputs for a source build."""

import base64
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from typing import TypedDict, cast


ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "out/inputs"
JDK = ROOT / "out/jdk"


class Artifact(TypedDict):
    filename: str
    url: str
    sha256: str
    license: str


class Source(TypedDict):
    url: str
    sha256: str


class Profile(TypedDict):
    commit: str
    modules: dict[str, Source]
    files: dict[str, Source]


class Lock(TypedDict):
    api_database_sha256: str
    jdk: Artifact
    data: Artifact
    protoc: Artifact
    runtime: list[Artifact]
    compile: list[Artifact]
    kotlin: list[Artifact]
    profiles: dict[str, Profile]


def load_lock() -> Lock:
    return cast(Lock, json.loads((ROOT / "locks/inputs.json").read_text()))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def tree_digest(path: Path) -> str:
    # Gitiles regenerates tar headers, so pin the paths, modes and contents.
    entries: dict[str, tuple[str, int, str]] = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if member.name in entries or not (member.isfile() or member.isdir()):
                raise ValueError(f"Unexpected source archive member: {member.name}")
            stream = archive.extractfile(member)
            content = ""
            if stream is not None:
                with stream:
                    content = sha256(stream.read()).hexdigest()
            entries[member.name] = (member.type.decode("ascii"), member.mode, content)
    return sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fetch(
    path: Path, url: str, expected: str, *, source: bool = False, text: bool = False
) -> None:
    checksum = tree_digest if source else digest
    if path.is_file() and checksum(path) == expected:
        return
    if not url.startswith("https://"):
        raise ValueError(f"Expected an HTTPS URL: {url}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    try:
        subprocess.run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--retry",
                "3",
                "--output",
                str(temporary),
                url,
            ],
            check=True,
        )
        if text:
            temporary.write_bytes(base64.b64decode(temporary.read_bytes()))
        if checksum(temporary) != expected:
            raise ValueError(f"SHA-256 mismatch for {url}")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_artifact(entry: Artifact, group: str) -> None:
    fetch(CACHE / group / entry["filename"], entry["url"], entry["sha256"])


def fetch_profile(version: str, profile: Profile) -> None:
    target = CACHE / version
    for module, entry in profile["modules"].items():
        fetch(target / f"{module}.tar.gz", entry["url"], entry["sha256"], source=True)
    for filename, entry in profile["files"].items():
        fetch(target / filename, entry["url"], entry["sha256"], text=True)


def install_jdk(entry: Artifact) -> None:
    marker = JDK / ".archive-sha256"
    if marker.is_file() and marker.read_text().strip() == entry["sha256"]:
        return
    with TemporaryDirectory(dir=JDK.parent) as temporary:
        staged = Path(temporary) / "jdk"
        with tarfile.open(CACHE / entry["filename"], "r:gz") as archive:
            archive.extractall(staged, filter="data")
        (staged / marker.name).write_text(entry["sha256"] + "\n")
        if JDK.exists():
            shutil.rmtree(JDK)
        staged.replace(JDK)


def main() -> None:
    lock = load_lock()
    if sys.argv[1:] == ["--compiler-inputs"]:
        print(CACHE / "compiler" / lock["protoc"]["filename"])
        print(
            os.pathsep.join(
                str(CACHE / group / entry["filename"])
                for group, entries in (
                    ("runtime", lock["runtime"]),
                    ("compile", lock["compile"]),
                )
                for entry in entries
            )
        )
        print(
            os.pathsep.join(
                [
                    *(
                        str(CACHE / "kotlin" / entry["filename"])
                        for entry in lock["kotlin"]
                    ),
                    str(CACHE / "runtime/annotations-23.0.0.jar"),
                ]
            )
        )
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--source-archives":
        version = sys.argv[2]
        for module in lock["profiles"][version]["modules"]:
            print(CACHE / version / f"{module}.tar.gz")
        return
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = [
            pool.submit(fetch_artifact, lock["jdk"], "."),
            pool.submit(fetch_artifact, lock["data"], "data"),
            pool.submit(fetch_artifact, lock["protoc"], "compiler"),
        ]
        for group in ("runtime", "compile", "kotlin"):
            entries = lock[group]
            jobs.extend(pool.submit(fetch_artifact, entry, group) for entry in entries)
        for version, profile in lock["profiles"].items():
            jobs.append(pool.submit(fetch_profile, version, profile))
        for job in jobs:
            job.result()
    install_jdk(lock["jdk"])


if __name__ == "__main__":
    main()
