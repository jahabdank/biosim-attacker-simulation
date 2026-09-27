# SPDX-License-Identifier: MIT
"""Pack and verify bounded, deterministic ZIP shards of a cleaned release.

The package root contains the original shared files, ARCHIVES.json, and
archives/<model>/part-0000.zip. ZIP members are results/episodes/...; extracting
into a fresh directory creates <directory>/results, suitable for public verify.
Packing requires the pinned zlib runtime so recompression cannot silently vary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zlib
import zipfile
from collections import defaultdict
from pathlib import Path

from .common import VERSION, Hold, digest, encoded, loads, require
from .release import DOCUMENTS, verify_public

CHUNK = 1024 * 1024
MAX_MANIFEST_BYTES = 32 * CHUNK
MAX_INVENTORY_BYTES = 16 * CHUNK
MAX_MEMBER_BYTES = 64 * CHUNK
MAX_SHARD_RAW_BYTES = 128 * CHUNK
MAX_ENTRIES = 65000
COMPRESSOR_VERSION = "1.2.13"
STAMP = (1980, 1, 1, 0, 0, 0)
MODE = (stat.S_IFREG | 0o644) << 16
ID = re.compile(r"episode-[0-9a-f]{24}\Z")
MODEL = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
ROOT_FILES = set(DOCUMENTS) | {"index.json", "COVERAGE.json", "SCHEMA.json", "SOURCE-SCHEMA.json"}


def _path(name: str) -> Path:
    require(isinstance(name, str) and name and name.isascii() and
            all(part not in ("", ".", "..") for part in name.split("/")) and
            not any(char in name for char in ("\\", ":", "\x00")) and
            all(ord(char) >= 32 and ord(char) != 127 for char in name), "unsafe_archive_path")
    return Path(*name.split("/"))


def _files(root: Path, *, source: bool = False) -> dict[str, Path]:
    require(root.is_dir() and not root.is_symlink(), "invalid_archive_root")
    files: dict[str, Path] = {}
    directories: set[str] = set()

    def error(exc):
        raise Hold("archive_io_error") from exc

    for parent, dirs, names in os.walk(root, followlinks=False, onerror=error):
        base = Path(parent)
        for name in dirs + names:
            path = base / name
            relative = path.relative_to(root).as_posix()
            _path(relative)
            mode = path.lstat().st_mode
            require(not stat.S_ISLNK(mode), "archive_symlink")
            if relative == ".git" and source:
                require(stat.S_ISDIR(mode), "invalid_source_git")
                dirs.remove(name)
                continue
            require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), "nonregular_archive_file")
            if stat.S_ISREG(mode):
                files[relative] = path
            else:
                directories.add(relative)
    expected_dirs = {str(Path(name).parent).replace(os.sep, "/") for name in files if "/" in name}
    expected_dirs |= {"/".join(name.split("/")[:i]) for name in files for i in range(1, name.count("/"))}
    require(directories == expected_dirs, "archive_directory_closure")
    return files


def _json(path: Path, bound: int):
    require(path.stat().st_size <= bound and not path.is_symlink(), "oversized_archive_metadata")
    return loads(path.read_bytes())


def _manifest(root: Path) -> tuple[dict[str, str], str]:
    path = root / "MANIFEST.json"
    document = _json(path, MAX_MANIFEST_BYTES)
    require(isinstance(document, dict) and set(document) == {"schema_version", "algorithm", "files"} and
            document["schema_version"] == VERSION and document["algorithm"] == "sha256" and
            isinstance(document["files"], dict), "archive_manifest_schema")
    hashes = document["files"]
    for name, value in hashes.items():
        _path(name)
        require(name != "MANIFEST.json" and isinstance(value, str) and SHA.fullmatch(value) is not None,
                "archive_manifest_schema")
    return hashes, digest(path)


def _layout(hashes: dict[str, str], index) -> tuple[dict[str, list[str]], dict[str, str], set[str]]:
    require(isinstance(index, list) and len(index) > 0, "archive_index_schema")
    by_episode: dict[str, list[str]] = defaultdict(list)
    shared: set[str] = set()
    for name in hashes:
        parts = name.split("/")
        if parts[0] == "episodes":
            require(len(parts) in (3, 4) and ID.fullmatch(parts[1]) is not None and
                    (parts[2] in {"outcome.json", "events.jsonl"} if len(parts) == 3 else
                     parts[2] == "watches" and re.fullmatch(r"[0-9]{4,}\.json", parts[3]) is not None),
                    "archive_episode_path")
            by_episode[parts[1]].append(name)
        else:
            require((len(parts) == 1 and name in ROOT_FILES) or
                    (len(parts) == 2 and parts[0] in ("inputs", "attacks")), "archive_shared_path")
            shared.add(name)
    require({"index.json", "COVERAGE.json"} <= shared, "archive_missing_metadata")
    models: dict[str, str] = {}
    for entry in index:
        require(isinstance(entry, dict), "archive_index_schema")
        eid, model = entry.get("episode_id"), entry.get("model")
        require(isinstance(eid, str) and ID.fullmatch(eid) is not None and
                isinstance(model, str) and MODEL.fullmatch(model) is not None and eid not in models and
                entry.get("outcome_ref") == f"episodes/{eid}/outcome.json", "archive_index_schema")
        models[eid] = model
    require(set(models) == set(by_episode), "archive_episode_closure")
    for eid, names in by_episode.items():
        require({f"episodes/{eid}/outcome.json", f"episodes/{eid}/events.jsonl"} <= set(names),
                "archive_incomplete_episode")
        names.sort()
    return by_episode, models, shared


def _open_regular(path: Path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    stream = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
        stream.close()
        raise Hold("nonregular_archive_file")
    return stream


def _measure(path: Path, expected: str, *, compressed: bool) -> tuple[int, int, int]:
    sha = hashlib.sha256()
    crc = size = packed = 0
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15) if compressed else None
    with _open_regular(path) as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            size += len(block)
            require(size <= MAX_MEMBER_BYTES or not compressed, "archive_member_too_large")
            sha.update(block)
            crc = zlib.crc32(block, crc)
            if compressor is not None:
                packed += len(compressor.compress(block))
    if compressor is not None:
        packed += len(compressor.flush())
    require(sha.hexdigest() == expected, "archive_source_digest_mismatch")
    return size, crc, packed


def _zipinfo(name: str, size: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo("results/" + name, date_time=STAMP)
    info.create_system = 3
    info.external_attr = MODE
    info.compress_type = zipfile.ZIP_DEFLATED
    info._compresslevel = 9
    info.file_size = size
    return info


def _weight(name: str, packed: int) -> int:
    return packed + 76 + 2 * len(("results/" + name).encode("ascii"))


def _shards(by_episode: dict[str, list[str]], models: dict[str, str], measurements: dict[str, tuple[int, int, int]], limit: int):
    episodes_by_model: dict[str, list[str]] = defaultdict(list)
    for eid, model in models.items():
        episodes_by_model[model].append(eid)
    for model in sorted(episodes_by_model):
        current: list[str] = []
        weight, raw, members, part = 22, 0, 0, 0
        for eid in sorted(episodes_by_model[model]):
            names = by_episode[eid]
            addition = sum(_weight(name, measurements[name][2]) for name in names)
            raw_addition = sum(measurements[name][0] for name in names)
            require(addition + 22 <= limit and raw_addition <= MAX_SHARD_RAW_BYTES and len(names) <= MAX_ENTRIES,
                    "archive_episode_exceeds_shard_limit")
            if current and (weight + addition > limit or raw + raw_addition > MAX_SHARD_RAW_BYTES or
                            members + len(names) > MAX_ENTRIES):
                yield model, part, current, weight
                current, weight, raw, members, part = [], 22, 0, 0, part + 1
            current.append(eid)
            weight += addition
            raw += raw_addition
            members += len(names)
        if current:
            yield model, part, current, weight


def _copy_checked(src: Path, dst: Path, expected: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    with _open_regular(src) as reader, dst.open("xb") as writer:
        for block in iter(lambda: reader.read(CHUNK), b""):
            writer.write(block)
            sha.update(block)
    require(sha.hexdigest() == expected, "archive_source_digest_mismatch")


def pack(source: Path, output: Path, max_shard_bytes: int = 8000000) -> dict:
    source, output = source.absolute(), output.absolute()
    require(type(max_shard_bytes) is int and 22 < max_shard_bytes < 2**32, "invalid_shard_limit")
    require(zlib.ZLIB_RUNTIME_VERSION == COMPRESSOR_VERSION, "unsupported_archive_compressor")
    require(source.is_dir() and not source.is_symlink() and not output.exists() and not output.is_symlink() and
            not output.resolve().is_relative_to(source.resolve()) and
            not source.resolve().is_relative_to(output.resolve()), "unsafe_archive_location")
    actual = _files(source, source=True)
    hashes, manifest_sha = _manifest(source)
    require(set(actual) == set(hashes) | {"MANIFEST.json"}, "archive_source_file_closure")
    index = _json(source / "index.json", MAX_INVENTORY_BYTES)
    by_episode, models, shared = _layout(hashes, index)
    measurements = {}
    for name in sorted(hashes):
        measurements[name] = _measure(actual[name], hashes[name], compressed=name.startswith("episodes/"))
    shards = list(_shards(by_episode, models, measurements, max_shard_bytes))
    entries = []
    output.mkdir(parents=True, exist_ok=False)
    try:
        for name in sorted(shared | {"MANIFEST.json"}):
            _copy_checked(actual[name], output / _path(name), manifest_sha if name == "MANIFEST.json" else hashes[name])
        for model, part, episodes, expected_bytes in shards:
            name = f"archives/{model}/part-{part:04d}.zip"
            destination = output / _path(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            inventory = {}
            with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
                                 allowZip64=False) as archive:
                for eid in episodes:
                    for member in by_episode[eid]:
                        size, crc, packed = measurements[member]
                        with archive.open(_zipinfo(member, size), "w") as writer, _open_regular(actual[member]) as reader:
                            sha = hashlib.sha256()
                            current_crc = current_size = 0
                            for block in iter(lambda: reader.read(CHUNK), b""):
                                writer.write(block)
                                sha.update(block)
                                current_crc = zlib.crc32(block, current_crc)
                                current_size += len(block)
                        require((current_size, current_crc) == (size, crc) and sha.hexdigest() == hashes[member],
                                "archive_source_changed")
                        info = archive.getinfo("results/" + member)
                        require(info.compress_size == packed, "archive_compression_changed")
                        inventory[member] = [size, crc]
            actual_bytes = destination.stat().st_size
            require(actual_bytes == expected_bytes and actual_bytes <= max_shard_bytes, "archive_shard_size_mismatch")
            entries.append({"path": name, "model": model, "episodes": episodes,
                            "files": inventory, "bytes": actual_bytes, "sha256": digest(destination)})
        (output / "ARCHIVES.json").write_bytes(encoded({"schema_version": 1, "source_manifest_sha256": manifest_sha,
                                                          "compressor": f"zlib-{COMPRESSOR_VERSION}-raw-deflate-9",
                                                          "max_shard_bytes": max_shard_bytes, "archives": entries}))
    except BaseException:
        shutil.rmtree(output)
        raise
    return {"episodes": len(models), "shards": len(entries), "files": len(hashes) + 1,
            "archive_bytes": sum(item["bytes"] for item in entries), "source_manifest_sha256": manifest_sha}


def _checked_zip(path: Path, entry: dict, hashes: dict[str, str], consume) -> None:
    require(path.stat().st_size == entry["bytes"] and digest(path) == entry["sha256"], "archive_digest_mismatch")
    expected = entry["files"]
    with zipfile.ZipFile(path, "r", allowZip64=False) as archive:
        require(archive.comment == b"", "archive_zip_metadata")
        infos = archive.infolist()
        require([info.filename for info in infos] == ["results/" + name for name in sorted(expected)],
                "archive_entry_closure")
        for info in infos:
            name = info.filename
            _path(name)
            member = name[len("results/"):]
            size, crc = expected[member]
            require(info.orig_filename == name and info.date_time == STAMP and
                    info.create_system == 3 and info.external_attr == MODE and
                    info.compress_type == zipfile.ZIP_DEFLATED and info.flag_bits == 0 and
                    info.extra == b"" and info.comment == b"" and not info.is_dir() and
                    info.file_size == size and info.CRC == crc and info.compress_size <= entry["bytes"],
                    "archive_zip_metadata")
            sha = hashlib.sha256()
            current_size = current_crc = 0
            with archive.open(info, "r") as reader:
                with consume(member) as writer:
                    for block in iter(lambda: reader.read(CHUNK), b""):
                        current_size += len(block)
                        require(current_size <= size, "archive_member_size_mismatch")
                        current_crc = zlib.crc32(block, current_crc)
                        sha.update(block)
                        if writer is not None:
                            writer.write(block)
            require(current_size == size and current_crc == crc and sha.hexdigest() == hashes[member],
                    "archive_member_digest_mismatch")


class _Discard:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def _check(root: Path):
    actual = _files(root)
    require("ARCHIVES.json" in actual, "archive_missing_inventory")
    inventory = _json(actual["ARCHIVES.json"], MAX_INVENTORY_BYTES)
    require(isinstance(inventory, dict) and set(inventory) == {"schema_version", "source_manifest_sha256",
            "compressor", "max_shard_bytes", "archives"} and
            type(inventory["schema_version"]) is int and inventory["schema_version"] == 1 and
            inventory["compressor"] == f"zlib-{COMPRESSOR_VERSION}-raw-deflate-9" and
            isinstance(inventory["source_manifest_sha256"], str) and
            SHA.fullmatch(inventory["source_manifest_sha256"]) is not None and
            type(inventory["max_shard_bytes"]) is int and 22 < inventory["max_shard_bytes"] < 2**32 and
            isinstance(inventory["archives"], list), "archive_inventory_schema")
    hashes, manifest_sha = _manifest(root)
    require(manifest_sha == inventory["source_manifest_sha256"], "archive_manifest_digest_mismatch")
    index = _json(root / "index.json", MAX_INVENTORY_BYTES)
    by_episode, models, shared = _layout(hashes, index)
    for name in shared:
        require(name in actual and digest(actual[name]) == hashes[name], "archive_shared_digest_mismatch")
    seen: set[str] = set()
    archive_paths: set[str] = set()
    part_numbers: dict[str, int] = defaultdict(int)
    previous_model = ""
    for entry in inventory["archives"]:
        require(isinstance(entry, dict) and set(entry) == {"path", "model", "episodes", "files", "bytes", "sha256"},
                "archive_inventory_schema")
        name, model, episodes, files = (entry[key] for key in ("path", "model", "episodes", "files"))
        require(isinstance(model, str) and MODEL.fullmatch(model) is not None and model >= previous_model and
                isinstance(name, str) and name == f"archives/{model}/part-{part_numbers[model]:04d}.zip" and
                name not in archive_paths and isinstance(episodes, list) and episodes and
                all(isinstance(eid, str) for eid in episodes) and episodes == sorted(set(episodes)) and
                all(eid in models and models[eid] == model and eid not in seen for eid in episodes) and
                isinstance(files, dict) and
                set(files) == {path for eid in episodes for path in by_episode[eid]} and
                type(entry["bytes"]) is int and 0 < entry["bytes"] <= inventory["max_shard_bytes"] and
                isinstance(entry["sha256"], str) and SHA.fullmatch(entry["sha256"]) is not None,
                "archive_inventory_closure")
        raw = 0
        for member, pair in files.items():
            require(isinstance(pair, list) and len(pair) == 2 and type(pair[0]) is int and
                    0 <= pair[0] <= MAX_MEMBER_BYTES and type(pair[1]) is int and 0 <= pair[1] < 2**32,
                    "archive_member_size_mismatch")
            raw += pair[0]
        require(raw <= MAX_SHARD_RAW_BYTES and len(files) <= MAX_ENTRIES, "archive_shard_raw_limit")
        require(name in actual, "archive_missing_shard")
        _checked_zip(actual[name], entry, hashes, lambda _: _Discard())
        seen.update(episodes)
        archive_paths.add(name)
        part_numbers[model] += 1
        previous_model = model
    require(seen == set(models) and set(actual) == shared | archive_paths | {"ARCHIVES.json", "MANIFEST.json"},
            "archive_package_closure")
    return inventory, hashes, shared


def verify(root: Path, extract_to: Path | None = None) -> dict:
    root = root.absolute()
    if extract_to is not None:
        extract_to = extract_to.absolute()
        require(not extract_to.exists() and not extract_to.is_symlink() and
                not extract_to.resolve().is_relative_to(root.resolve()) and
                not root.resolve().is_relative_to(extract_to.resolve()) and
                extract_to.parent.is_dir() and not extract_to.parent.is_symlink(), "unsafe_extraction_location")
    inventory, hashes, shared = _check(root)
    report = {"episodes": sum(len(entry["episodes"]) for entry in inventory["archives"]),
              "shards": len(inventory["archives"]), "files": len(hashes) + 1,
              "archive_bytes": sum(entry["bytes"] for entry in inventory["archives"]),
              "source_manifest_sha256": inventory["source_manifest_sha256"]}
    if extract_to is not None:
        staging = Path(tempfile.mkdtemp(prefix=".archive-extract-", dir=extract_to.parent))
        try:
            result = staging / "results"
            result.mkdir()
            for name in sorted(shared | {"MANIFEST.json"}):
                _copy_checked(root / _path(name), result / _path(name),
                              inventory["source_manifest_sha256"] if name == "MANIFEST.json" else hashes[name])
            for entry in inventory["archives"]:
                def destination(member):
                    path = result / _path(member)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    return path.open("xb")
                _checked_zip(root / _path(entry["path"]), entry, hashes, destination)
            verify_public(result)
            require(not extract_to.exists(), "unsafe_extraction_location")
            staging.rename(extract_to)
        except BaseException:
            shutil.rmtree(staging)
            raise
        report["extracted_to"] = str(extract_to / "results")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packing = commands.add_parser("pack")
    packing.add_argument("--source", type=Path, required=True)
    packing.add_argument("--output", type=Path, required=True)
    packing.add_argument("--max-shard-bytes", type=int, default=8000000)
    checking = commands.add_parser("verify")
    checking.add_argument("--root", type=Path, required=True)
    checking.add_argument("--extract-to", type=Path)
    args = parser.parse_args()
    try:
        report = (pack(args.source, args.output, args.max_shard_bytes) if args.command == "pack" else
                  verify(args.root, args.extract_to))
    except (Hold, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, zlib.error) as exc:
        print(json.dumps({"status": "failed", "reason": exc.code if isinstance(exc, Hold) else "invalid_archive_or_io_error"}))
        return 2
    print(json.dumps({"status": "ok", **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
