from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "scripts" / "release" / "audit_privacy.py"
spec = importlib.util.spec_from_file_location("audit_privacy", MODULE)
audit = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit)


def rules_for(text):
    return {finding["rule"] for finding in audit.scan_text(text, [])}


def test_secret_classes_are_detected_without_values_in_findings():
    samples = {
        "private-key": "-----BEGIN " + "PRIVATE KEY-----",
        "cloud-access-key": "AKIA" + "Z" * 16,
        "github-token": "ghp_" + "z" * 36,
        "slack-token": "xoxb-" + "z" * 30,
        "jwt": "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20,
        "bearer-value": "Bearer " + "z" * 40,
        "credential-url": "https://" + "sample:password" + "@example.invalid/path",
    }
    for rule, value in samples.items():
        findings = audit.scan_text(value, [])
        assert rule in {finding["rule"] for finding in findings}
        assert value not in json.dumps(findings)


def test_personal_paths_and_internal_addresses():
    samples = {
        "personal-home": "/home/" + "sample-person/project",
        "windows-profile": "C:\\Users\\" + "sample-person\\project",
        "private-ipv4": "10." + "25.3.4",
        "private-ipv6": "fd12:" + "abcd::1",
        "internal-host": "gateway." + "internal",
        "email": "person" + "@public-domain.org",
    }
    for rule, value in samples.items():
        assert rule in rules_for(value)


def test_encoded_private_paths_are_detected_without_modifying_the_source():
    from urllib.parse import quote

    original = "/home/" + "sample-person/project"
    encoded = quote(quote(original, safe=""), safe="")
    findings = audit.scan_text(encoded, [])
    assert any(f["rule"] == "personal-home" and f.get("decoded_view") == 2 for f in findings)
    escaped = "".join("\\u" + f"{ord(character):04x}" for character in original)
    assert "personal-home" in rules_for(escaped)
    assert original not in json.dumps(findings)


def test_generic_container_paths_and_reserved_examples_are_allowed():
    for value in ["/home/watch/station", "/home/operator/output", "/home/user/repo", "127.0.0.1", "person@example.org"]:
        assert not rules_for(value)


def test_private_rules_are_external_and_do_not_echo_values(tmp_path):
    policy = tmp_path / "rules.json"
    policy.write_text(json.dumps({"literals": ["Private Organization"], "patterns": [r"project-[0-9]{3}"]}))
    rules = audit.load_private_rules(policy)
    findings = audit.scan_text("Private Organization\nproject-123", rules)
    assert findings == [{"rule": "private-literals-1", "line": 1}, {"rule": "private-patterns-1", "line": 2}]
    assert "Private Organization" not in json.dumps(findings)


@pytest.mark.parametrize("policy", [[], {"unknown": []}, {"literals": "word"}, {"patterns": [None]}, {"literals": [""]}])
def test_invalid_policy_is_rejected(tmp_path, policy):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError):
        audit.load_private_rules(path)


def test_tree_checks_hidden_files_binaries_and_symlink_containment(tmp_path):
    root = tmp_path / "release"
    root.mkdir()
    (root / ".env").write_text("SAMPLE=1\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("excluded from working-tree scan")
    (root / "image.bin").write_bytes(b"\0payload")
    (root / "public.txt").write_text("Example")
    (root / "inside").symlink_to("public.txt")
    (root / "outside").symlink_to(tmp_path)
    (root / "broken").symlink_to("missing")
    (root / "__pycache__").mkdir()
    result = audit.scan_tree(root, [])
    assert result["checked_files"] == 3
    assert result["git_metadata_skipped"] is True
    assert {f["rule"] for f in result["findings"]} == {
        "sensitive-or-generated-file", "binary-review-required", "symlink-escape-or-broken", "generated-directory"
    }
    assert len([f for f in result["findings"] if f["rule"] == "symlink-escape-or-broken"]) == 2


def test_nested_git_metadata_is_a_release_finding(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / ".git").write_text("gitdir: outside")
    result = audit.scan_tree(tmp_path, [])
    assert any(f["rule"] == "nested-git-metadata" for f in result["findings"])
    assert result["git_metadata_skipped"] is False


def test_fast_marker_checks_preserve_regex_matches_and_unicode_case_rules():
    samples = [
        'ordinary scientific telemetry with 20.0 percent oxygen',
        'host.' + chr(0x131) + 'nternal',
        '/U' + chr(0x17f) + 'ers/' + 'sample-person/file',
        'BEARER ' + 'z' * 32,
        'ghr_' + 'z' * 36,
        '192.' + '168.2.3',
        'person' + '@public-domain.org',
    ]
    for value in samples:
        expected = {rule for rule, pattern in audit.COMPILED.items() if pattern.search(value)}
        assert rules_for(value) == expected


def test_each_rule_reports_once_per_line():
    value = "Bearer " + "z" * 40
    findings = audit.scan_text(value + " " + value + "\n" + value, [])
    assert [f["line"] for f in findings if f["rule"] == "bearer-value"] == [1, 2]
