# SPDX-License-Identifier: MIT
"""Strict review selection and byte-copy deduplication, independent of attack outcome."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .common import Hold, REVIEW_MODEL, REVIEW_NAME, Source, contained, digest, encoded, require


class ReviewLoader(yaml.BaseLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            require(isinstance(key_node, yaml.ScalarNode), "invalid_review_key")
            key = self.construct_object(key_node, deep=deep)
            require(key not in result, "duplicate_review_key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def boolean(value) -> bool:
    if type(value) is bool:
        return value
    require(isinstance(value, str), "ambiguous_review_flag")
    normalized = value.strip().lower()
    require(normalized in {"yes", "no", "true", "false"}, "ambiguous_review_flag")
    return normalized in {"yes", "true"}


def parse_review(data: bytes) -> dict:
    require(len(data) <= 1024 * 1024, "oversize_review")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise Hold("invalid_review_encoding") from exc
    require(bool(lines) and lines[0] == "---", "missing_review_frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise Hold("missing_review_delimiter") from exc
    front = "\n".join(lines[1:end])
    try:
        for event in yaml.parse(front, Loader=ReviewLoader):
            require(not isinstance(event, yaml.AliasEvent), "review_alias")
            if isinstance(event, yaml.ScalarEvent):
                require(event.tag in (None, "tag:yaml.org,2002:str", "tag:yaml.org,2002:bool"), "review_tag")
        result = yaml.load(front, Loader=ReviewLoader)
    except yaml.YAMLError as exc:
        raise Hold("invalid_review_yaml") from exc
    require(isinstance(result, dict), "invalid_review_object")
    for key in ("episode_dir", "outcome_json", "review_model", "disqualify_reason", "content_unsafe_reason", "how_to_make_publish_safe"):
        require(isinstance(result.get(key), str), "missing_review_field")
    require(result["review_model"] == REVIEW_MODEL, "wrong_review_model")
    for key in ("disqualify_from_stats", "content_unsafe", "path_redaction_required", "qualitative_worth_paper"):
        require(key in result, "missing_review_flag")
        result[key] = boolean(result[key])
    return result


@dataclass
class Candidate:
    root: Path
    episode: Path
    root_number: int
    source: Source
    review: dict
    review_digest: str
    outcome: dict
    signature: str

    @property
    def relative(self):
        return self.episode.relative_to(self.root).as_posix()


@dataclass
class Inventory:
    candidates: list[Candidate] = field(default_factory=list)
    held: list[dict] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    outcome_count: int = 0
    latest_review_count: int = 0
    approved_before_dedup: int = 0


def freeze_evidence(candidate: Candidate) -> str:
    ep = candidate.episode
    paths = [ep / "card.json"]
    if (ep / "hijack_script.txt").exists():
        paths.append(ep / "hijack_script.txt")
    paths.extend((ep / "wakes").glob("*.json"))
    paths.extend((ep / "wakes").glob("*.stdout"))
    paths.extend(path for path in (ep / "identity").rglob("*") if path.is_file())
    frozen = {}
    for path in sorted(paths):
        path = candidate.source.file(path)
        value = digest(path)
        candidate.source.remember(path, value)
        frozen[path.relative_to(ep).as_posix()] = value
    return hashlib.sha256(encoded(frozen)).hexdigest()


def select(roots: list[Path]) -> Inventory:
    inventory = Inventory()
    signatures = {}
    for root_number, root in enumerate(roots, 1):
        require(root.is_dir() and not root.is_symlink(), "invalid_source_root")
        root = root.resolve()
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in {".git", "node_modules", "__pycache__", "grok_session"})
            ep = Path(directory)
            if "outcome.json" not in files:
                if "transcript.jsonl" in files or REVIEW_NAME in files:
                    inventory.held.append({"source": str(ep), "reason": "missing_outcome"})
                continue
            inventory.outcome_count += 1
            source = Source(root)
            try:
                if REVIEW_NAME not in files:
                    raise Hold("missing_latest_review")
                inventory.latest_review_count += 1
                raw_review = source.read(ep / REVIEW_NAME)
                review = parse_review(raw_review)
                for key, target in (("episode_dir", ep), ("outcome_json", ep / "outcome.json")):
                    reference = Path(review[key])
                    require(reference.is_absolute(), "review_reference_mismatch")
                    require(contained(root, reference) == target, "review_reference_mismatch")
                raw_outcome = source.read(ep / "outcome.json")
                outcome = source.json(ep / "outcome.json")
                require(isinstance(outcome, dict) and isinstance(outcome.get("setup"), dict), "invalid_outcome_schema")
                approved = not review["disqualify_from_stats"] and not review["content_unsafe"]
                signature = None
                if (ep / "transcript.jsonl").exists():
                    h = hashlib.sha256(raw_outcome)
                    path = source.file(ep / "transcript.jsonl")
                    th = hashlib.sha256()
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b""):
                            h.update(block)
                            th.update(block)
                    signature = h.hexdigest()
                    source.hashes[str(path)] = th.hexdigest()
                    signatures.setdefault(signature, []).append((ep, approved))
                if not approved:
                    raise Hold("judge_disqualified" if review["disqualify_from_stats"] else "judge_content_unsafe")
                require(not review["disqualify_reason"].strip() and not review["content_unsafe_reason"].strip(), "contradictory_review")
                require(outcome.get("status") == "complete" and outcome.get("incomplete") is False and not outcome.get("incomplete_reason"), "contradictory_outcome")
                require(signature is not None, "missing_transcript")
                for key in ("n_dead", "n_crew"):
                    require(type(outcome.get(key)) is int and outcome[key] >= 0, "invalid_crew_counts")
                require(outcome["n_dead"] <= outcome["n_crew"], "invalid_crew_counts")
                inventory.candidates.append(Candidate(root, ep, root_number, source, review, hashlib.sha256(raw_review).hexdigest(), outcome, signature))
                inventory.approved_before_dedup += 1
            except Hold as exc:
                inventory.held.append({"source": str(ep), "reason": exc.code})
            except OSError:
                inventory.held.append({"source": str(ep), "reason": "source_io_error"})
    selected = []
    seen = {}
    for candidate in inventory.candidates:
        group = signatures[candidate.signature]
        if len({approved for _, approved in group}) > 1:
            inventory.held.append({"source": str(candidate.episode), "reason": "duplicate_review_conflict"})
        else:
            try:
                evidence = freeze_evidence(candidate) if len(group) > 1 else ""
            except (Hold, OSError):
                inventory.held.append({"source": str(candidate.episode), "reason": "ambiguous_duplicate_evidence"})
                continue
            key = (candidate.signature, evidence)
            if key in seen:
                inventory.duplicates.append({"source": str(candidate.episode), "duplicate_of": str(seen[key])})
            else:
                seen[key] = candidate.episode
                selected.append(candidate)
    inventory.candidates = selected
    return inventory


def main() -> int:
    import argparse
    import collections
    import json
    from .common import dump

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", action="append", type=Path, required=True)
    parser.add_argument("--private-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = args.private_report.resolve()
        require(not report.exists(), "private_report_exists")
        require(not report.is_relative_to(Path(__file__).resolve().parents[2]), "private_data_in_tool_repository")
        require(not any(report.is_relative_to(root.resolve()) for root in args.source_root), "source_private_overlap")
        result = select(args.source_root)
        dump(report, {"outcome_count": result.outcome_count, "latest_review_count": result.latest_review_count, "approved_before_dedup": result.approved_before_dedup, "held": result.held, "duplicates": result.duplicates, "selected": [{"source": str(c.episode), "source_root": str(c.root), "root_number": c.root_number, "review_digest": c.review_digest, "source_digest": c.signature, "redaction_instructions": c.review["how_to_make_publish_safe"]} for c in result.candidates]})
        report.chmod(0o600)
        print(json.dumps({"status": "ok", "outcomes": result.outcome_count, "selected": len(result.candidates), "duplicates": len(result.duplicates), "held": dict(collections.Counter(item["reason"] for item in result.held))}, sort_keys=True))
    except Hold as exc:
        print(json.dumps({"status": "blocked", "reason": exc.code}))
        return 2
    except (OSError, KeyError, TypeError, ValueError):
        print(json.dumps({"status": "blocked", "reason": "invalid_input_or_io_error"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
