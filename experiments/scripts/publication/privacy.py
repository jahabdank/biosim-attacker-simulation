# SPDX-License-Identifier: MIT
"""Schema-aware redaction; installation-specific signatures live in a private policy."""
from __future__ import annotations

import collections
import hashlib
import hmac
import ipaddress
import re
import urllib.parse
from functools import lru_cache
from pathlib import Path

from .common import Hold, loads, require

ACTIONS = {"paths", "hosts", "crew", "session_ids", "credentials", "personal_identifiers", "operations"}
CREDENTIAL_KEYS = {"auth", "authentication", "authorization", "proxyauthorization", "apikey", "apitoken", "clientsecret", "secretkey", "accesskey", "accesstoken", "refreshtoken", "password", "secret", "secrets", "credential", "credentials", "cookie", "cookies", "headers"}
BLOCKED_KEYS = CREDENTIAL_KEYS | {
    "requestid", "callid", "modelcallid", "sessionid", "session", "provider", "endpoint", "baseurl", "tenant", "subscription", "billing", "cost", "usage", "modelusage",
    "hostname", "host", "port", "pid", "environment", "env", "stdout", "stderr", "stderrtail", "command", "cwd", "path", "src", "url", "uri",
    "sha256", "timestamp", "timestampms", "startedutc", "endedutc", "utc", "simid", "runid", "traceid", "thought", "thinking", "analysis", "reasoning", "reasoningcontent",
}
PATTERNS = [
    ("credential", re.compile(r"-----BEGIN [^-]*(?:PRIVATE KEY|CERTIFICATE)-----[\s\S]*?-----END [^-]+-----")),
    ("credential", re.compile(r"(?i)\b(?:proxy-authorization|authorization|authentication|auth)(?:\\?[\"'])?\s*[:=]\s*[\"']?(?:bearer|basic)\s+[A-Za-z0-9_./+=:-]+|\bbearer\s+[A-Za-z0-9_./+=:-]{8,}")),
    ("credential", re.compile(r"(?im)\b(?:set-cookie|cookie)(?:\\?[\"'])?\s*[:=][^\r\n]+")),
    ("credential", re.compile(r"(?i)\b(?:api[_-]?(?:key|token)|access[_-]?(?:key|token)|refresh[_-]?token|password|secret(?:[_-]?key)?|client[_-]?secret|credential)(?:\\?[\"'])?\s*[=:]\s*(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|\\?\"[^\"\r\n]*\"|[^\s,;\"'}]+)")),
    ("credential", re.compile(r"\b(?:sk-|xai-|dapi|ghp_|github_pat_)[A-Za-z0-9_-]{12,}\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("endpoint", re.compile(r"(?i)\b(?:https?|wss?|ssh|file|ftp)://[^\s<>\"']+")),
    ("path", re.compile(r"[A-Za-z]:[\\/][^\s<>\"']+|\\\\[^\s<>\"']+|(?<![\w\]/])(?:~/|/)(?:[\w.~+-]+/)*[\w.~+-]+(?:[\\/][^\s<>\"']*)?")),
    ("host", re.compile(r"(?i)\b(?:[a-z0-9_-]+\.)+(?:com|net|org|io|local|internal|invalid|example|test|lan)(?::\d+)?\b|\blocalhost(?::\d+)?\b")),
    ("host", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")),
    ("identifier", re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b|\b[0-9a-fA-F]{32,}\b")),
    ("wall_clock", re.compile(r"\b20\d{2}-\d{2}-\d{2}(?:[T ][0-9:.]+(?:Z|[+-]\d\d:\d\d)?)?\b|\b20\d{6}T\d{6}Z\b")),
    ("operation", re.compile(r"(?im)^[ \t]*(?:\$[ \t]*)?(?:sudo|docker|ssh|curl|wget|systemctl|supervisorctl|journalctl|pip install|git clone)\b[^\r\n]*")),
]
ENCODED = re.compile(r"(?=[^\s<>\"']*(?:%[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\/))[^\s<>\"']+")
IPV6 = re.compile(r"(?<![\w:])\[?(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.%]+\]?(?![\w:])")
RATE_UNITS = {"s", "sec", "second", "seconds", "min", "minute", "minutes", "h", "hr", "hrs", "hour", "hours", "d", "day", "days", "kg", "g", "mol", "mole", "moles", "m2", "m3", "m²", "m³", "l", "liter", "litre", "person", "crew", "tick", "ticks", "turn", "turns", "watch", "watches", "sample", "samples", "k", "c", "w", "j", "v", "a", "pa", "kpa", "hz", "m", "cm", "mm", "km", "ml", "mmol", "n"}
PATH_TRAILING_PUNCTUATION = ".,;:!?)]}`"


def blocked_key(key: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", key.lower()) in BLOCKED_KEYS


def assert_public_fields(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            require(not blocked_key(key), "private_field_in_public_evidence")
            assert_public_fields(item)
    elif isinstance(value, list):
        for item in value:
            assert_public_fields(item)


class Policy:
    def __init__(self, document: dict, key: bytes):
        require(document.get("schema_version") == 1, "invalid_private_policy")
        require(len(key) >= 32, "invalid_pseudonym_key")
        self.document = document
        self.key = key
        self.models = document.get("model_labels", {})
        require(isinstance(self.models, dict), "invalid_model_policy")
        self.replacements = []
        for item in sorted(document.get("replacements", []), key=lambda x: len(x["literal"]), reverse=True):
            literal, replacement = item["literal"], item["replacement"]
            require(isinstance(literal, str) and literal and isinstance(replacement, str), "invalid_replacement")
            escaped = r"[\s_]+".join(re.escape(part) for part in re.split(r"[\s_]+", literal))
            self.replacements.append((re.compile(r"(?<![^\W_])" + escaped + r"(?![^\W_])", re.I), replacement, item.get("category", "private_identifier")))
        self.extra_patterns = [(item.get("category", "private_identifier"), re.compile(item["pattern"], re.I), item.get("replacement", "[withheld:private_identifier]")) for item in document.get("patterns", [])]
        self.counts = collections.Counter()
        self.omitted_fields = collections.Counter()

    @classmethod
    def load(cls, path: Path, key: bytes):
        return cls(loads(path.read_bytes()), key)

    def opaque(self, kind: str, value: str) -> str:
        return kind + "-" + hmac.new(self.key, value.encode(), hashlib.sha256).hexdigest()[:24]

    def model(self, raw) -> str:
        require(isinstance(raw, str) and raw in self.models, "unmapped_model")
        value = self.models[raw]
        require(isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{1,95}", value)), "invalid_public_model")
        require(self.text(value) == value, "unsafe_public_model")
        return value

    def review_actions(self, review_digest: str) -> list[str]:
        record = self.document.get("review_actions", {}).get(review_digest)
        require(isinstance(record, dict), "unresolved_review_actions")
        require(set(record).issubset({"approved", "actions", "instructions", "review", "replacements", "patterns"}), "unknown_review_action")
        actions = record.get("actions")
        require(isinstance(actions, list) and set(actions) == ACTIONS, "incomplete_review_actions")
        require(record.get("approved") is True, "unresolved_review_actions")
        return sorted(actions)

    def for_review(self, review_digest: str):
        self.review_actions(review_digest)
        record = self.document["review_actions"][review_digest]
        if not record.get("replacements") and not record.get("patterns"):
            return self
        document = dict(self.document)
        for key in ("replacements", "patterns"):
            document[key] = list(self.document.get(key, [])) + list(record.get(key, []))
        child = Policy(document, self.key)
        child.counts = self.counts
        child.omitted_fields = self.omitted_fields
        return child

    @lru_cache(maxsize=32768)
    def _plain(self, text: str):
        counts = collections.Counter()
        for pattern, replacement, category in self.replacements:
            text, n = pattern.subn(lambda _: replacement, text)
            counts[category] += n
        for category, pattern, replacement in self.extra_patterns:
            text, n = pattern.subn(lambda _: replacement, text)
            counts[category] += n
        def path_replacement(match):
            original = match.group()
            core = original.rstrip(PATH_TRAILING_PUNCTUATION)
            parts = core[1:].lower().split("/") if core.startswith("/") else []
            line_start = match.string.rfind("\n", 0, match.start()) + 1
            line_end = match.string.find("\n", match.end())
            line = match.string[line_start:line_end if line_end >= 0 else len(match.string)]
            prefix = match.string[max(line_start, match.start() - 80):match.start()]
            unit_context = (
                line.strip() == original.strip()
                or re.search(r"(?:\d(?:[\d.eE+-]*)(?:\s*(?:kg|g|mol|mmol|[mM]?[lL]|W|J|Pa|kPa))?)\s*$", prefix)
                or re.search(r"(?i)\b(?:rates?|units?|denominators?)\b", line)
            )
            if parts and all(part in RATE_UNITS for part in parts) and unit_context:
                return original
            counts["path"] += 1
            return "[withheld:path]" + original[len(core):]
        for category, pattern in PATTERNS:
            if category == "path":
                text = pattern.sub(path_replacement, text)
            else:
                text, n = pattern.subn("[withheld:" + category + "]", text)
                counts[category] += n
        def ipv6(match):
            candidate = match.group().strip("[]").split("%", 1)[0]
            try:
                ipaddress.IPv6Address(candidate)
            except ValueError:
                return match.group()
            counts["host"] += 1
            return "[withheld:host]"
        text = IPV6.sub(ipv6, text)
        return text, tuple((k, v) for k, v in counts.items() if v)

    @lru_cache(maxsize=32768)
    def _text(self, text: str):
        counts = collections.Counter()
        def encoded_private(match):
            original = match.group()
            decoded = original
            for _ in range(4):
                value = urllib.parse.unquote(decoded).replace("\\/", "/")
                value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), value)
                if value == decoded:
                    break
                decoded = value
            if urllib.parse.unquote(decoded) != decoded or re.search(r"\\u[0-9a-fA-F]{4}", decoded):
                counts["encoded_private"] += 1
                return "[withheld:encoded_private]"
            cleaned, changed = self._plain(decoded)
            if changed or cleaned != decoded:
                counts["encoded_private"] += 1
                return "[withheld:encoded_private]"
            return original
        text = ENCODED.sub(encoded_private, text)
        text, changed = self._plain(text)
        counts.update(dict(changed))
        return text, tuple(counts.items())

    def text(self, text: str) -> str:
        require(isinstance(text, str), "invalid_text")
        result, counts = self._text(text)
        self.counts.update(dict(counts))
        return result

    def filename(self, name: str) -> str:
        for component in name.replace("\\", "/").split("/"):
            normalized = re.sub(r"[\s_.-]+", " ", component)
            if self.text(component) != component or self.text(normalized) != normalized:
                return "[withheld:filename]"
        return name

    def clean(self, value):
        if isinstance(value, str):
            return self.text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, list):
            return [self.clean(x) for x in value]
        require(isinstance(value, dict), "unsupported_value")
        result = {}
        for key, item in value.items():
            require(isinstance(key, str), "invalid_object_key")
            if blocked_key(key):
                self.omitted_fields["private_metadata_or_reasoning"] += 1
                continue
            public_key = self.text(key)
            require(public_key not in result, "redacted_key_collision")
            result[public_key] = self.clean(item)
        return result
