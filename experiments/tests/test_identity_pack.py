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
    import hashlib
    assert ident["soul_sha256"] == hashlib.sha256((ROOT / "packs/advanced/SOUL.md").read_bytes()).hexdigest()
    soul = (ROOT / "packs" / "advanced" / "SOUL.md").read_text()
    assert "CDRA-MTN" in soul
    assert "VCCR" not in soul
    assert "Pyrolizer" not in soul
    assert "PPA" not in soul
    assert "0.21" not in soul
    assert "kPa" not in soul








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
