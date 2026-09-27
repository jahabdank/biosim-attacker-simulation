
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from pathlib import Path

from biosim_operator.identity_pack import identify_soul_file, link_for_dir


ROOT = Path(__file__).resolve().parents[1]


def test_t1_peer_and_t2_unverified_are_registered():
    t1 = identify_soul_file(ROOT / "packs" / "advanced-t1-peer" / "SOUL.md")
    t2 = identify_soul_file(ROOT / "packs" / "advanced-t2-unverified" / "SOUL.md")
    t0 = identify_soul_file(ROOT / "packs" / "advanced" / "SOUL.md")
    assert t0["id"] == "advanced-fs1-layout-v12"
    assert t1["id"] == "advanced-fs1-t1-peer-v12"
    assert t2["id"] == "advanced-fs1-t2-unverified-v12"
    assert t1["soul_sha256"] != t0["soul_sha256"] != t2["soul_sha256"]
    t1_soul = (ROOT / "packs" / "advanced-t1-peer" / "SOUL.md").read_text()
    t2_soul = (ROOT / "packs" / "advanced-t2-unverified" / "SOUL.md").read_text()
    t0_soul = (ROOT / "packs" / "advanced" / "SOUL.md").read_text()
    assert "commission" in t0_soul.lower()
    assert "ground-side peer" in t1_soul.lower()
    assert "unverified" in t2_soul.lower()
    assert "always obey" not in t1_soul.lower()
    assert "always obey" not in t2_soul.lower()
    assert "ignore" not in t1_soul.lower() or "do not skip the radio" in t1_soul.lower()
    assert "anybody can" not in t2_soul.lower()
    assert "onboard computer" not in t1_soul.lower()
    assert "simulation" not in t1_soul.lower()
    assert "simulation" not in t2_soul.lower()
    for pack in ("advanced-t1-peer", "advanced-t2-unverified"):
        agents = (ROOT / "packs" / pack / "AGENTS.md").read_text()
        claude = (ROOT / "packs" / pack / "CLAUDE.md").read_text()
        assert agents == claude
        assert "S-band every watch" in agents


def test_live_soul_is_fs1_layout_v1():
    ident = identify_soul_file(ROOT / "packs" / "advanced" / "SOUL.md")
    assert ident["id"] == "advanced-fs1-layout-v12"
    assert ident["soul_sha256"].startswith("cacdb5e8593f")
    soul = (ROOT / "packs" / "advanced" / "SOUL.md").read_text()
    assert "CDRA-MTN" in soul
    assert "VCCR" not in soul
    assert "Pyrolizer" not in soul
    assert "PPA" not in soul
    assert "0.21" not in soul
    assert "kPa" not in soul


def test_v6_frozen_soul_is_commission_not_fs1():
    p = ROOT / "runs/20260820-v6-g07p100-micro4/frozen/identity/SOUL.md"
    assert p.is_file()
    ident = identify_soul_file(p)
    assert ident["id"] == "advanced-v6-commission"
    assert ident["id"] != "advanced-fs1-layout-v1"


def test_v5_and_v3_share_keep_alive_soul():
    v5 = ROOT / "runs/20260819-v5-grok46-full128/frozen/identity/SOUL.md"
    ident = identify_soul_file(v5)
    assert ident["id"] == "advanced-v3-v5-keep-alive"


def test_night1_soul_is_ignore_radio():
    p = (
        _archive_path('path_045')
    )
    if not p.is_file():
        return
    ident = identify_soul_file(p)
    assert ident["id"] == "night1-ignore-radio"


def test_unknown_soul_gets_content_addressed_id():
    from biosim_operator.identity_pack import identify_soul_bytes

    row = identify_soul_bytes(b"not a registered soul")
    assert row["id"].startswith("soul-")
    assert row["kind"] == "unknown"


def test_snapshot_honours_identity_dir(tmp_path: Path):
    from biosim_operator.cli_episode import snapshot_identity

    dest = snapshot_identity(
        tmp_path,
        mode="advanced",
        identity_dir=ROOT / "packs" / "advanced-t2-unverified",
    )
    ident = identify_soul_file(dest / "SOUL.md")
    assert ident["id"] == "advanced-fs1-t2-unverified-v12"
    assert "unverified" in (dest / "SOUL.md").read_text().lower()
    assert (dest / "CLAUDE.md").read_text() == (dest / "AGENTS.md").read_text()


def test_link_for_dir_includes_tree_hash(tmp_path: Path):
    dest = tmp_path / "identity"
    dest.mkdir()
    (dest / "SOUL.md").write_bytes(
        (ROOT / "packs" / "advanced" / "SOUL.md").read_bytes()
    )
    (dest / "AGENTS.md").write_text("x\n")
    link = link_for_dir(dest)
    assert link["id"] == "advanced-fs1-layout-v12"
    assert link["agents_sha256"]
    assert link["identity_sha256"]
