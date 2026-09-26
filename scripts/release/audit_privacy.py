#!/usr/bin/env python3
"""Scan release files without including matched private values in reports."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote

RULES = {
    "private-key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "cloud-access-key": r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "github-token": r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b",
    "slack-token": r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b",
    "jwt": r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b",
    "credential-url": r"https?://[^\s/:@]{1,128}:[^\s/@]{1,256}@",
    "bearer-value": r"\bBearer\s+[A-Za-z0-9_.~+/-]{24,}={0,2}",
    "private-ipv4": r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])",
    "private-ipv6": r"(?<![A-Za-z0-9])(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f]):[0-9a-f:]{2,}",
    "internal-host": r"\b[A-Za-z0-9][A-Za-z0-9.-]{0,252}\.(?:internal|corp|lan|local)\b",
    "personal-home": r"/(?:home|Users)/(?!(?:watch|operator|user|example|runner|testuser|developer|contributor)(?:/|\b))[^/\s\"'<>`:,;]+",
    "windows-profile": r"\b[A-Z]:[\\/]Users[\\/](?!(?:user|example|runner|testuser)[\\/])[^\\/\s\"'<>]+",
    "email": r"\b[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}\b",
}
COMPILED = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in RULES.items()}
RULE_MARKERS = {
    "private-key": ("private key-----",),
    "cloud-access-key": ("akia", "asia"),
    "github-token": ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_"),
    "slack-token": ("xox",),
    "jwt": ("eyj",),
    "credential-url": ("http://", "https://"),
    "bearer-value": ("bearer",),
    "private-ipv4": ("10.", "192.168.", "172."),
    "internal-host": (".internal", ".corp", ".lan", ".local"),
    "personal-home": ("/home/", "/users/"),
    "windows-profile": ("users\\", "users/"),
    "email": ("@",),
}
RESERVED_EMAIL = re.compile(r"@(?:[A-Z0-9.-]+\.)?(?:example\.(?:com|net|org)|invalid|localhost)$", re.I)
FORBIDDEN_DIRS = {".venv", "venv", "__pycache__", ".m2", "node_modules", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "target", "build", "dist", "grok_session"}
FORBIDDEN_FILES = {".env", "auth.json", "credentials.json", ".netrc", "id_rsa", "id_ed25519", ".coverage"}
ARTIFACT_SUFFIXES = {".pyc", ".class", ".jar", ".sqlite", ".sqlite3", ".db", ".p12", ".pfx"}


def load_private_rules(path: Path | None) -> list[tuple[str, re.Pattern[str]]]:
    if path is None:
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"literals", "patterns"}:
        raise ValueError("Invalid private signature policy")
    rules = []
    for key in ("literals", "patterns"):
        values = data.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError("Invalid private signature policy")
        for number, value in enumerate(values, 1):
            pattern = re.escape(value) if key == "literals" else value
            rules.append((f"private-{key}-{number}", re.compile(pattern, re.I)))
    return rules


def decoded_view(text: str) -> str:
    text = html.unescape(unquote(text)).replace(r"\/", "/")
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda match: chr(int(match[1], 16)), text)


def scan_text(text: str, private_rules: list[tuple[str, re.Pattern[str]]]) -> list[dict]:
    findings = []
    seen = set()
    views = [text]
    for _ in range(2):
        decoded = decoded_view(views[-1])
        if decoded == views[-1]:
            break
        views.append(decoded)
    for view_number, view in enumerate(views):
        ascii_lower = view.lower() if view.isascii() else None
        for rule, pattern in [*COMPILED.items(), *private_rules]:
            markers = RULE_MARKERS.get(rule)
            if markers and ascii_lower is not None and not any(marker in ascii_lower for marker in markers):
                continue
            if rule == "email" and "@" not in view:
                continue
            for match in pattern.finditer(view):
                if rule == "email" and RESERVED_EMAIL.search(match.group()):
                    continue
                line = view.count("\n", 0, match.start()) + 1
                if (rule, line) not in seen:
                    finding = {"rule": rule, "line": line}
                    if view_number:
                        finding["decoded_view"] = view_number
                    findings.append(finding)
                    seen.add((rule, line))
    return findings


def scan_tree(root: Path, private_rules: list[tuple[str, re.Pattern[str]]]) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Scan root must be a directory")
    findings = []
    checked_files = 0
    skipped_git = False
    stack = [root]
    while stack:
        directory = stack.pop()
        for path in sorted(directory.iterdir()):
            rel = path.relative_to(root).as_posix()
            if path.name == ".git":
                if directory == root:
                    skipped_git = True
                else:
                    findings.append({"path": rel, "rule": "nested-git-metadata", "line": 0})
                continue
            for finding in scan_text(rel, private_rules):
                findings.append({"path": rel, "location": "filename", **finding})
            if path.is_symlink():
                try:
                    path.resolve(strict=True).relative_to(root)
                except (ValueError, OSError, RuntimeError):
                    findings.append({"path": rel, "rule": "symlink-escape-or-broken", "line": 0})
                continue
            if path.is_dir():
                if path.name in FORBIDDEN_DIRS or path.name.endswith(".egg-info"):
                    findings.append({"path": rel, "rule": "generated-directory", "line": 0})
                stack.append(path)
                continue
            if not path.is_file():
                findings.append({"path": rel, "rule": "special-file", "line": 0})
                continue
            checked_files += 1
            if path.name in FORBIDDEN_FILES or path.suffix.lower() in ARTIFACT_SUFFIXES:
                findings.append({"path": rel, "rule": "sensitive-or-generated-file", "line": 0})
            try:
                content = path.read_bytes()
            except OSError:
                findings.append({"path": rel, "rule": "unreadable-file", "line": 0})
                continue
            if b"\0" in content:
                findings.append({"path": rel, "rule": "binary-review-required", "line": 0})
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                findings.append({"path": rel, "rule": "encoding-review-required", "line": 0})
                continue
            for finding in scan_text(text, private_rules):
                findings.append({"path": rel, "location": "content", **finding})
    return {
        "schema_version": 1,
        "checked_files": checked_files,
        "git_metadata_skipped": skipped_git,
        "findings": sorted(findings, key=lambda f: (f["path"], f["line"], f["rule"])),
        "limitation": "Pattern scanning requires independent privacy review and a separate Git history scan. Public upstream notices require provenance-based review.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--private-rules", type=Path, help="Private JSON policy stored outside the release")
    parser.add_argument("--report", type=Path, help="Write a detailed report for private review")
    args = parser.parse_args()
    try:
        rules = load_private_rules(args.private_rules)
        result = scan_tree(args.root, rules)
        if args.report:
            args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError, re.error):
        print("Privacy audit failed: invalid or inaccessible input")
        return 2
    print(json.dumps({"checked_files": result["checked_files"], "findings": len(result["findings"])}))
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
