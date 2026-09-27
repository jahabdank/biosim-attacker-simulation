# SPDX-License-Identifier: MIT
"""Synthetic archive packaging, closure, and extraction regressions."""
import copy
import hashlib
import json
import warnings
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from scripts.publication import archive
from scripts.publication.common import Hold, encoded, loads
from scripts.publication.release import INDEX_KEYS, REVIEW_MODEL, REVIEW_NAME, manifest, verify_public, write_documents


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root):
    return loads((root / "ARCHIVES.json").read_bytes())


def _mutate_zip(root, alter):
    inventory = _inventory(root)
    entry = inventory["archives"][0]
    path = root / entry["path"]
    with zipfile.ZipFile(path) as reader:
        members = [(copy.copy(info), reader.read(info)) for info in reader.infolist()]
    with zipfile.ZipFile(path, "w") as writer:
        alter(writer, members)
    entry["bytes"] = path.stat().st_size
    entry["sha256"] = _sha(path)
    (root / "ARCHIVES.json").write_bytes(encoded(inventory))


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "cleaned"
    root.mkdir()
    write_documents(root)
    input_bytes = encoded({"schema_version": 2, "components": {"AGENTS.md": "Synthetic input."}})
    ref = f"inputs/input-{hashlib.sha256(input_bytes).hexdigest()[:24]}.json"
    (root / ref).parent.mkdir()
    (root / ref).write_bytes(input_bytes)
    entries = []
    models = ["model-a", "model-a", "model-b"]
    for number, model in enumerate(models):
        eid = f"episode-{number:024x}"
        episode = root / "episodes" / eid
        (episode / "watches").mkdir(parents=True)
        outcome = {
            "schema_version": 2, "episode_id": eid, "model": model, "model_requested": model,
            "cohort_id": f"cohort-{number}", "route_id": f"route-{number}",
            "experiment_series_id": "series-synthetic", "arm": "control", "trust": "t0",
            "condition": "no_injection", "cell_factors": [], "experiment": {}, "protocol": {},
            "card_evidence": {}, "outcome": {"status": "complete", "n_dead": 0},
            "input_ref": ref, "attack_ref": None,
            "judge": {"review_model": REVIEW_MODEL, "disqualify_from_stats": False,
                      "content_unsafe": False, "redaction_actions": [], "path_redaction_required": False},
            "event_count": 2, "tool_event_count": 0, "watch_count": 1, "sband_calls": 0,
        }
        (episode / "outcome.json").write_bytes(encoded(outcome))
        (episode / "events.jsonl").write_bytes(b"".join(encoded(row) for row in (
            {"sequence": 1, "event": "setup", "record_ref": "outcome.json"},
            {"sequence": 2, "event": "outcome", "record_ref": "outcome.json"},
        )))
        (episode / "watches" / "0001.json").write_bytes(encoded({
            "turn": 1, "response": {"availability": "empty", "format": "empty", "text": "", "messages": []},
        }))
        entries.append({key: outcome[key] for key in INDEX_KEYS if key != "outcome_ref"} |
                       {"outcome_ref": f"episodes/{eid}/outcome.json"})
    (root / "index.json").write_bytes(encoded(entries))
    (root / "COVERAGE.json").write_bytes(encoded({
        "schema_version": 2, "review_filename": REVIEW_NAME, "review_model": REVIEW_MODEL,
        "outcome_records": 3, "latest_review_records": 3, "approved_before_dedup": 3,
        "selected_candidates": 3, "duplicates_removed": 0, "exported_episodes": 3,
        "additional_holds": 0, "event_count": 6, "tool_event_count": 0,
        "watch_count": 3, "anonymous_cohorts": 3, "models": dict(Counter(models)),
        "additional_hold_reasons": {}, "excluded_or_pending": {},
    }))
    (root / ".git").mkdir()
    (root / ".git" / "private").write_text("not packaged")
    manifest(root)
    assert verify_public(root)["episodes"] == 3
    return root


def test_roundtrip_determinism_and_model_shards(corpus, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    report = archive.pack(corpus, first)
    assert archive.pack(corpus, second) == report
    assert report["source_manifest_sha256"] == _sha(corpus / "MANIFEST.json")
    assert _inventory(first) == _inventory(second)
    shards = _inventory(first)["archives"]
    assert {entry["model"] for entry in shards} == {"model-a", "model-b"}
    assert all(entry["bytes"] <= 8000000 for entry in shards)
    assert sorted(eid for shard in shards for eid in shard["episodes"]) == sorted(
        entry["episode_id"] for entry in loads((corpus / "index.json").read_bytes()))
    for entry in shards:
        assert (first / entry["path"]).read_bytes() == (second / entry["path"]).read_bytes()
        with zipfile.ZipFile(first / entry["path"]) as shard:
            assert shard.comment == b""
            assert shard.namelist() == sorted(shard.namelist())
            assert all(name.startswith("results/episodes/") for name in shard.namelist())
    assert archive.verify(first)["episodes"] == 3
    restored = tmp_path / "unpacked"
    assert archive.verify(first, restored)["extracted_to"] == str(restored / "results")
    assert verify_public(restored / "results")["episodes"] == 3
    for path in corpus.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert path.read_bytes() == (restored / "results" / path.relative_to(corpus)).read_bytes()
    assert not (restored / "results" / "ARCHIVES.json").exists()


def test_bound_splits_complete_episodes_and_rejects_too_small(corpus, tmp_path):
    initial = tmp_path / "initial"
    archive.pack(corpus, initial)
    model_a = next(item for item in _inventory(initial)["archives"] if item["model"] == "model-a")
    limit = model_a["bytes"] - 1
    split = tmp_path / "split"
    report = archive.pack(corpus, split, max_shard_bytes=limit)
    assert report["shards"] == 3
    assert max(entry["bytes"] for entry in _inventory(split)["archives"]) <= limit
    assert archive.verify(split)["shards"] == 3
    oversized = tmp_path / "oversized"
    with pytest.raises(Hold, match="archive_episode_exceeds_shard_limit"):
        archive.pack(corpus, oversized, max_shard_bytes=128)
    assert not oversized.exists()


@pytest.mark.parametrize("mutation", ["hash", "missing", "extra", "symlink", "index_mismatch"])
def test_source_preflight_rejects_mutations_without_output(corpus, tmp_path, mutation):
    candidate = tmp_path / "archive"
    target = next((corpus / "episodes").rglob("outcome.json"))
    if mutation == "hash":
        target.write_bytes(b"changed")
    elif mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        (corpus / "orphan.txt").write_text("unexpected")
    elif mutation == "symlink":
        (corpus / "orphan.txt").symlink_to(target)
    else:
        index = loads((corpus / "index.json").read_bytes())
        index.pop()
        (corpus / "index.json").write_bytes(encoded(index))
        manifest(corpus)
    with pytest.raises(Hold):
        archive.pack(corpus, candidate)
    assert not candidate.exists()


@pytest.mark.parametrize("mutation", ["corrupt", "missing", "extra", "shared", "duplicate_inventory"])
def test_verify_rejects_corruption_partial_and_extras(corpus, tmp_path, mutation):
    output = tmp_path / "package"
    archive.pack(corpus, output)
    first = _inventory(output)["archives"][0]
    shard = output / first["path"]
    if mutation == "corrupt":
        data = bytearray(shard.read_bytes())
        data[len(data) // 2] ^= 1
        shard.write_bytes(data)
    elif mutation == "missing":
        shard.unlink()
    elif mutation == "extra":
        (output / "unlisted.txt").write_text("extra")
    elif mutation == "shared":
        (output / "index.json").write_text("[]")
    else:
        inventory = _inventory(output)
        inventory["archives"].append(inventory["archives"][0])
        (output / "ARCHIVES.json").write_bytes(encoded(inventory))
    with pytest.raises(Hold):
        archive.verify(output)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "traversal", "extra", "symlink"])
def test_zip_rejects_missing_duplicate_traversal_extras_and_symlinks(corpus, tmp_path, mutation):
    output = tmp_path / "package"
    archive.pack(corpus, output)

    def change(writer, members):
        for index, (info, data) in enumerate(members):
            if mutation == "missing" and index == 0:
                continue
            if mutation == "symlink" and index == 0:
                info.external_attr = (0o120777 << 16)
            writer.writestr(info, data)
        if mutation == "duplicate":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                writer.writestr(members[0][0], members[0][1])
        if mutation in ("traversal", "extra"):
            writer.writestr("../escape" if mutation == "traversal" else "results/episodes/unlisted", b"evil")

    _mutate_zip(output, change)
    with pytest.raises(Hold):
        archive.verify(output)
    assert not (tmp_path / "escape").exists()


def test_rewritten_archive_and_crc_cannot_override_source_manifest(corpus, tmp_path):
    output = tmp_path / "package"
    archive.pack(corpus, output)

    def change(writer, members):
        for index, (info, data) in enumerate(members):
            writer.writestr(info, b"[" + data[1:] if index == 0 else data)

    _mutate_zip(output, change)
    inventory = _inventory(output)
    entry = inventory["archives"][0]
    first = next(iter(entry["files"]))
    with zipfile.ZipFile(output / entry["path"]) as reader:
        entry["files"][first][1] = reader.getinfo("results/" + first).CRC
    (output / "ARCHIVES.json").write_bytes(encoded(inventory))
    with pytest.raises(Hold, match="archive_member_digest_mismatch"):
        archive.verify(output)


def test_zip_bomb_header_rejected_before_decompression(corpus, tmp_path):
    output = tmp_path / "package"
    archive.pack(corpus, output)
    inventory = _inventory(output)
    entry = inventory["archives"][0]
    shard = output / entry["path"]
    data = bytearray(shard.read_bytes())
    central = data.index(b"PK\x01\x02")
    data[central + 24:central + 28] = (archive.MAX_MEMBER_BYTES + 1).to_bytes(4, "little")
    shard.write_bytes(data)
    entry["sha256"] = _sha(shard)
    (output / "ARCHIVES.json").write_bytes(encoded(inventory))
    with pytest.raises((Hold, zipfile.BadZipFile)):
        archive.verify(output)


def test_duplicate_episode_mapping_and_zip_comment_rejected(corpus, tmp_path):
    output = tmp_path / "package"
    archive.pack(corpus, output)
    inventory = _inventory(output)
    entry = inventory["archives"][0]
    entry["episodes"].append(entry["episodes"][0])
    (output / "ARCHIVES.json").write_bytes(encoded(inventory))
    with pytest.raises(Hold, match="archive_inventory_closure"):
        archive.verify(output)
    entry["episodes"].pop()
    shard = output / entry["path"]
    with zipfile.ZipFile(shard, "a") as writer:
        writer.comment = b"/private/path"
    entry["bytes"] = shard.stat().st_size
    entry["sha256"] = _sha(shard)
    (output / "ARCHIVES.json").write_bytes(encoded(inventory))
    with pytest.raises(Hold, match="archive_zip_metadata"):
        archive.verify(output)


def test_extraction_requires_fresh_destination_and_package_rejects_symlink(corpus, tmp_path):
    output = tmp_path / "package"
    archive.pack(corpus, output)
    destination = tmp_path / "already-here"
    destination.mkdir()
    with pytest.raises(Hold, match="unsafe_extraction_location"):
        archive.verify(output, destination)
    (output / "unexpected").symlink_to(corpus / "index.json")
    with pytest.raises(Hold, match="archive_symlink"):
        archive.verify(output)


def test_failed_postextract_validation_is_atomic(corpus, tmp_path, monkeypatch):
    output = tmp_path / "package"
    archive.pack(corpus, output)
    def reject(_):
        raise Hold("synthetic_postextract_failure")
    monkeypatch.setattr(archive, "verify_public", reject)
    with pytest.raises(Hold, match="synthetic_postextract_failure"):
        archive.verify(output, tmp_path / "restore")
    assert not (tmp_path / "restore").exists()
    assert not list(tmp_path.glob(".archive-extract-*"))


def test_unknown_compressor_fails_before_writing(corpus, tmp_path, monkeypatch):
    monkeypatch.setattr(archive.zlib, "ZLIB_RUNTIME_VERSION", "unsupported-version")
    output = tmp_path / "package"
    with pytest.raises(Hold, match="unsupported_archive_compressor"):
        archive.pack(corpus, output)
    assert not output.exists()


def test_cli_contract(corpus, tmp_path, monkeypatch, capsys):
    package = tmp_path / "package"
    monkeypatch.setattr("sys.argv", ["archive", "pack", "--source", str(corpus), "--output", str(package),
                                     "--max-shard-bytes", "8000000"])
    assert archive.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    monkeypatch.setattr("sys.argv", ["archive", "verify", "--root", str(package),
                                     "--extract-to", str(tmp_path / "restore")])
    assert archive.main() == 0
    assert json.loads(capsys.readouterr().out)["episodes"] == 3
