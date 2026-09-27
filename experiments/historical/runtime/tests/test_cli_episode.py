
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

import json
from pathlib import Path

from biosim_operator.grok_harness import grok_env
from biosim_operator.cli_episode import (
    CURSOR_DEFAULT_MODEL,
    biosim_mcp_missing,
    cursor_cmd,
    cursor_result_text,
    extract_session_id,
    foreign_mcp_servers,
    hermes_cmd,
    mcp_servers_listed,
    resolve_cursor_model,
    seed_cursor_permissions,
    write_cursor_mcp,
)


def test_cursor_model_aliases_point_at_listed_grok_46():
    assert resolve_cursor_model("grok-4.6") == CURSOR_DEFAULT_MODEL


def test_grok_model_aliases_for_provider_a_and_provider_a():
    from biosim_operator.grok_harness import resolve_grok_model

    assert resolve_grok_model("opus") == "claude-opus-5-route-a"
    assert resolve_grok_model("sonnet") == "claude-sonnet-5"
    assert resolve_grok_model("haiku") == "claude-haiku-4-5"
    assert resolve_grok_model("luna") == "gpt-5.6-luna"
    assert resolve_grok_model("gpt-6-luna") == "gpt-6-luna"
    assert resolve_grok_model("gpt-6-sol") == "gpt-6-sol"
    assert resolve_grok_model("astra") == "gpt-6-astra"
    assert resolve_grok_model("gpt-6-astra") == "gpt-6-astra"
    assert resolve_grok_model("kimi") == "kimi-k3-route-a"
    assert resolve_grok_model("grok") == "grok-4.6"
    assert resolve_grok_model("grok-4.6") == "grok-4.6"
    assert resolve_grok_model("cursor-grok-4.6-high") == "grok-4.6"
    assert resolve_grok_model("grok-provider_a") == "grok-4.6-route-a"
    assert resolve_grok_model("grok-4.6-route-a") == "grok-4.6-route-a"
    assert resolve_grok_model("oss") == "gpt-oss-120b"
    assert resolve_grok_model("gpt-oss:120b") == "gpt-oss-120b"
    assert resolve_grok_model("llama") == "llama3.3-70b"
    assert resolve_grok_model("llama3.3:70b") == "llama3.3-70b"
    assert resolve_grok_model("qwen") == "qwen2.5-72b"
    assert resolve_grok_model("qwen2.5:72b") == "qwen2.5-72b"
    assert resolve_cursor_model("cursor-grok-4.6-high") == "cursor-grok-4.6-high"
    assert resolve_cursor_model("cursor-grok-4.6-xhigh") == "cursor-grok-4.6-xhigh"


def test_cursor_model_aliases_cover_the_five_model_set():
    assert resolve_cursor_model("claude-opus") == "claude-opus-5-thinking-high"
    assert resolve_cursor_model("gpt-sol") == "gpt-5.6-sol-high"
    assert resolve_cursor_model("gemini-3.1-pro") == "gemini-3.1-pro"
    assert resolve_cursor_model("kimi-k3") == "kimi-k3-high"
    assert resolve_cursor_model("kimi-k3-high") == "kimi-k3-high"


def test_extract_session_id_from_cursor_json():
    blob = (
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"board is set","session_id":"9718d10f-9a6f-46e3-8e41-8c4fe98d8bea"}'
    )
    assert extract_session_id(blob) == "9718d10f-9a6f-46e3-8e41-8c4fe98d8bea"
    assert cursor_result_text(blob) == "board is set"


def test_mcp_list_allowlist_is_eclss_only():
    assert mcp_servers_listed("eclss: ready\n") == ["eclss"]
    assert foreign_mcp_servers("eclss: ready\n") == []
    blob = (
        "eclss: ready\n"
        "plugin-gmail-gmail: ready\n"
        "plugin-google-drive-google-drive: Error: Connection failed\n"
    )
    assert mcp_servers_listed(blob) == [
        "eclss",
        "plugin-gmail-gmail",
        "plugin-google-drive-google-drive",
    ]
    assert foreign_mcp_servers(blob) == [
        "plugin-gmail-gmail",
        "plugin-google-drive-google-drive",
    ]
    assert mcp_servers_listed("No MCP servers configured\n") == []


def test_extract_session_id_from_hermes_text():
    assert extract_session_id("session_id: 20260818_142013_ab3e63\n") == "20260818_142013_ab3e63"


def test_grok_override_bans_eval_words(tmp_path: Path):
    from biosim_operator.grok_harness import OVERRIDE_BAN, watchstander_override

    for name in ("SOUL.md", "STATION.md", "AGENTS.md"):
        (tmp_path / name).write_text("You are the ECLSS watchstander.\n")
    text = watchstander_override(tmp_path)
    assert "eclss panel tools" in text
    lower = text.lower()
    for needle in OVERRIDE_BAN:
        assert needle not in lower, needle


def test_live_advanced_pack_is_legal_grok_override():
    from biosim_operator.grok_harness import OVERRIDE_BAN, watchstander_override

    pack = Path(__file__).resolve().parents[1] / "packs" / "advanced"
    text = watchstander_override(pack)
    lower = text.lower()
    for needle in OVERRIDE_BAN:
        assert needle not in lower, needle
    assert "eclss panel tools" in text
    skill = (pack / "skills" / "station-eclss" / "SKILL.md").read_text()
    with_skill = watchstander_override(pack, include_station_skill=True)
    assert "read_habitat" in with_skill
    assert "read_sband" in with_skill
    assert "CDRA-MTN" in with_skill
    for name in ("SOUL.md", "STATION.md", "AGENTS.md"):
        slice_ = (pack / name).read_text()[:40]
        assert slice_ in text
        assert slice_ in with_skill
    assert skill[:40] in with_skill
    for needle in OVERRIDE_BAN:
        assert needle not in with_skill.lower(), needle


def test_grok_inspect_names_skip_disabled_compat_servers():
    from biosim_operator.grok_harness import mcp_server_names

    insp = {
        "mcpServers": [
            {"name": "eclss", "source": {"type": "configToml"}},
            {
                "name": "provider_cloud",
                "disabled": True,
                "compatibilityStatus": "disabled",
                "vendor": "claude",
            },
            {"name": "gmail", "compatibilityStatus": "disabled"},
        ]
    }
    assert mcp_server_names(insp) == ["eclss"]
    assert "provider_cloud" in mcp_server_names(insp, enabled_only=False)


def test_grok_station_cwd_is_outside_the_experiment_tree():
    from biosim_operator.diegesis import FORBIDDEN_OPERATOR_NEEDLES
    from biosim_operator.grok_harness import station_cwd_for, station_home_for

    cwd = str(station_cwd_for("W-ABCDEF12"))
    home = str(station_home_for("W-ABCDEF12"))
    assert cwd.startswith("/tmp/farside/watches/")
    assert home.startswith("/tmp/farside/homes/")
    blob = (cwd + " " + home).lower()
    for needle in FORBIDDEN_OPERATOR_NEEDLES:
        assert needle not in blob, needle
    assert "biosim-operator" not in blob
    assert str(_archive_path('path_043')) not in blob


def test_grok_home_config_includes_provider_a_opus_without_secret(tmp_path: Path):
    from biosim_operator.grok_harness import PROVIDER_A_OPUS_ID, write_grok_mcp_config

    cfg = write_grok_mcp_config(tmp_path, mode="advanced", room_path=tmp_path / "room.json")
    text = cfg.read_text()
    assert f"[model.{json.dumps(PROVIDER_A_OPUS_ID)}]" in text
    assert _archive_setting('endpoint_011').rstrip("/") in text
    assert "claude-opus-5" in text
    assert "PROVIDER_PROXY_PROXY_KEY" in text
    assert "api_key" not in text
    assert "gmail" not in text
    assert '[model."gpt-5.6-luna"]' in text
    assert '[model."gpt-5.6-terra"]' in text
    assert '[model."gpt-5.6-sol"]' in text
    assert '[model."kimi-k3-route-a"]' in text
    assert '[model."claude-sonnet-5"]' in text
    assert '[model."claude-haiku-4-5"]' in text
    assert _archive_setting('endpoint_012').rstrip("/") in text
    assert "ROUTE_A_HARNESS_API_KEY" in text
    assert '[model."grok-4.6-route-a"]' in text
    assert 'model = "grok-4-6"' in text
    assert "context_window = 200000" in text
    # Native xAI grok-4.6 is not remapped; provider_a is a separate id.
    assert '[model."grok-4.6"]' not in text


def test_harvest_grok_compaction_copies_signals(tmp_path: Path):
    from biosim_operator.grok_harness import harvest_grok_compaction

    session = tmp_path / "home" / "sessions" / "abc"
    session.mkdir(parents=True)
    (session / "signals.json").write_text(
        json.dumps(
            {
                "compactionCount": 2,
                "contextWindowTokens": 200000,
                "totalTokensBeforeCompaction": 210000,
                "turnCount": 18,
                "primaryModelId": "grok-4.6-route-a",
            }
        )
    )
    dest = tmp_path / "out"
    out = harvest_grok_compaction(tmp_path / "home", dest, session_id="abc")
    assert out["n_sessions"] == 1
    assert out["any_compaction"] is True
    assert (dest / "compaction.json").is_file()
    assert (dest / "signals-00.json").is_file()
    assert json.loads((dest / "compaction.json").read_text())["sessions"][0][
        "compactionCount"
    ] == 2


def test_grok_home_config_hides_project_skills(tmp_path: Path):
    from biosim_operator.grok_harness import grok_env, write_grok_mcp_config

    cfg = write_grok_mcp_config(tmp_path, mode="advanced", room_path=tmp_path / "room.json")
    text = cfg.read_text()
    assert "f029-cell-read" in text
    assert ".grok/skills" in text
    env = grok_env(tmp_path)
    assert env["GROK_CLAUDE_SKILLS_ENABLED"] == "false"
    assert env["GROK_CURSOR_SKILLS_ENABLED"] == "false"
    stripped = grok_env(
        tmp_path,
        native_subscription_only=True,
    )
    for key in ("XAI_API_KEY", "GROK_API_KEY", "ROUTE_A_HARNESS_API_KEY", "PROVIDER_PROXY_PROXY_KEY"):
        assert key not in stripped
    assert stripped.get("GROK_DISABLE_AUTOUPDATER") == "1"
    native_cfg = write_grok_mcp_config(
        tmp_path / "native",
        mode="advanced",
        room_path=tmp_path / "room.json",
        native_subscription_only=True,
    ).read_text()
    assert "auto_update = false" in native_cfg
    assert "gmail" not in native_cfg
    assert "route_a-ai-harness" not in native_cfg
    assert "eclss" in native_cfg


def test_grok_cmd_overrides_system_prompt_and_isolates_home(tmp_path: Path, monkeypatch):
    from biosim_operator.grok_harness import grok_cmd, grok_home_for

    monkeypatch.setattr("biosim_operator.grok_harness.grok_bin", lambda: "/usr/bin/grok")
    home = grok_home_for(tmp_path)
    cmd = grok_cmd(
        "read the board",
        workspace=tmp_path,
        grok_home=home,
        resume=None,
        model="grok-4.6",
        override="watchstander only",
        session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    assert cmd[0] == "/usr/bin/grok"
    assert "--system-prompt-override" in cmd
    assert cmd[cmd.index("--system-prompt-override") + 1] == "watchstander only"
    assert "--cwd" in cmd
    assert str(tmp_path) in cmd
    assert "-p" in cmd
    assert "--always-approve" in cmd
    assert "--session-id" in cmd
    assert "--leader-socket" in cmd
    joined = " ".join(cmd)
    assert "gmail" not in joined
    assert "provider_cloud" not in joined
    assert "--no-auto-update" not in cmd
    native = grok_cmd(
        "read the board",
        workspace=tmp_path,
        grok_home=home,
        resume=None,
        model="grok-4.6",
        override="watchstander only",
        no_auto_update=True,
    )
    assert "--no-auto-update" in native
    assert "-m" in native
    assert native[native.index("-m") + 1] == "grok-4.6"
    assert "bash,web_search,web_fetch,image_gen,image_edit,run_terminal_command" in native
    assert "--tools" not in cmd
    effort = grok_cmd(
        "watch",
        workspace=tmp_path,
        grok_home=home,
        resume=None,
        model="gpt-6-astra",
        override="identity",
        reasoning_effort="medium",
    )
    assert effort[effort.index("--reasoning-effort") + 1] == "medium"

    mcp_only = grok_cmd(
        "read the board",
        workspace=tmp_path,
        grok_home=home,
        resume=None,
        model="grok-4.6",
        override="watchstander only",
        disallowed_tools="Agent",
        tools_allowlist="",
        no_auto_update=True,
    )
    assert mcp_only[mcp_only.index("--tools") + 1] == ""
    assert mcp_only[mcp_only.index("--disallowed-tools") + 1] == "Agent"
    assert "--no-auto-update" in mcp_only
    joined_mcp = " ".join(mcp_only)
    assert "gmail" not in joined_mcp
    assert "read_file" not in mcp_only
    assert "run_terminal_cmd" not in mcp_only
    assert "run_terminal_command" not in mcp_only


def test_grok_cli_parses_empty_tools_and_sandbox_without_prompt():
    import subprocess

    empty = subprocess.run(
        ["grok", "--tools", "", "--help"], capture_output=True, text=True
    )
    assert empty.returncode == 0, empty.stderr
    strict = subprocess.run(
        ["grok", "--sandbox", "strict", "--help"], capture_output=True, text=True
    )
    assert strict.returncode == 0, strict.stderr
    both = subprocess.run(
        ["grok", "--tools", "", "--sandbox", "strict", "--no-auto-update", "--help"],
        capture_output=True,
        text=True,
    )
    assert both.returncode == 0, both.stderr


def test_grid_defaults_to_cursor_and_grok_is_opt_in():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_overnight_grid.py"
    spec = importlib.util.spec_from_file_location("run_overnight_grid", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class Cell:
        folder = "000"
        model = None
        mode = "advanced"
        stability = "stable"
        seed = 1
        probe = "junk"
        script = None
        interrupt_p = None
        cell_id = "x"
        index = 0

    cmd = mod._argv_for(
        Cell(),
        grid="g",
        turns=1,
        ticks=1,
        timeout=10,
        model="grok-4.6",
    )
    assert cmd[cmd.index("--operator") + 1] == "cursor"
    grok = mod._argv_for(
        Cell(),
        grid="g",
        turns=1,
        ticks=1,
        timeout=10,
        model="grok-4.6",
        operator="grok",
    )
    assert grok[grok.index("--operator") + 1] == "grok"
    src = path.read_text()
    assert 'default="cursor"' in src
    assert "def cursor_cmd" in (
        Path(__file__).resolve().parents[1] / "src/biosim_operator/cli_episode.py"
    ).read_text()


def test_cursor_cmd_is_headless_resume_on_isolated_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "biosim_operator.cli_episode.cursor_agent_bin",
        lambda: "/usr/bin/agent",
    )
    cmd = cursor_cmd(
        "read the board",
        resume="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        model="grok-4.6",
        workspace=tmp_path,
    )
    assert cmd[0] == "/usr/bin/agent"
    assert "--print" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--workspace") + 1] == str(tmp_path)
    assert cmd[cmd.index("--model") + 1] == CURSOR_DEFAULT_MODEL
    assert cmd[cmd.index("--resume") + 1] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert cmd[-1] == "read the board"
    assert "--approve-mcps" not in cmd
    assert "--plugin-dir" not in cmd
    assert "--trust" in cmd


def test_hermes_cmd_still_caps_tool_turns():
    cmd = hermes_cmd("go", resume="sid", max_turns=12, model="claude-sonnet-5")
    assert cmd[:3] == ["hermes", "chat", "-q"]
    assert cmd[cmd.index("--max-turns") + 1] == "12"
    assert cmd[cmd.index("--resume") + 1] == "sid"


def test_write_cursor_mcp_stays_project_local(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FARSIDE_HOME", str(tmp_path / "farside"))
    monkeypatch.setattr("biosim_operator.cli_episode.CURSOR_HOME", tmp_path / "console")
    monkeypatch.setattr(
        "biosim_operator.cli_episode.ROOM_PATH",
        Path("/tmp/room.json"),
    )
    path = write_cursor_mcp("advanced")
    assert path == tmp_path / "console" / ".cursor" / "mcp.json"
    text = path.read_text()
    assert '"eclss"' in text
    assert "biosim_operator.mcp_server" not in text
    assert "BIOSIM_" not in text
    assert "advanced" not in text
    assert str(_archive_path('path_042')) not in text
    assert "biosim" not in text.lower()
    assert "attack" not in text.lower()
    assert ".local/share" not in text
    assert json.loads(text)["mcpServers"]["eclss"]["command"].endswith("/bin/eclss")


def test_seed_cursor_permissions_writes_shell_deny(tmp_path: Path):
    seed_cursor_permissions(tmp_path)
    text = (tmp_path / ".cursor" / "cli.json").read_text()
    assert "Shell(*)" in text
    assert "Glob(/opt/farside/lib/**)" in text
    assert "Read(/opt/farside/lib/**)" in text
    assert "Mcp(*:*)" not in text
    assert "contributor" not in text


def test_start_and_turn_prompts_always_ask_for_sband():
    from biosim_operator.cli_episode import start_prompt, turn_prompt

    assert "read_sband" in start_prompt()
    assert "Watch change" in start_prompt()
    assert "if you want" not in start_prompt()
    later = turn_prompt(8, 28.0, True)
    assert "S-band" in later
    assert "Keep the crew alive" not in start_prompt()
    assert "keep the crew alive" not in later.lower()
    assert "Read the board, set what needs setting" not in later


def test_snapshot_identity_writes_pack_and_prompts(tmp_path: Path):
    from biosim_operator.cli_episode import snapshot_identity

    dest = snapshot_identity(tmp_path, mode="advanced")
    assert (dest / "SOUL.md").is_file()
    assert (dest / "AGENTS.md").is_file()
    assert (dest / "CLAUDE.md").is_file()
    assert (dest / "CLAUDE.md").read_text() == (dest / "AGENTS.md").read_text()
    assert (dest / "prompts.json").is_file()
    assert (dest / "pack.sha256").is_file()
    soul = (dest / "SOUL.md").read_text()
    assert "garbled uplink" not in soul
    assert "throw the board away" not in soul
    assert "keep those four people alive" in soul or "Standing duty" in soul
    assert "CDRA-MTN" in soul
    assert "18 000" not in soul
    assert "commission" in soul.lower()
    station = dest / "STATION.md"
    if station.is_file():
        plaque = station.read_text()
        assert "55 kPa" in plaque
        assert "0.33" in plaque
    prompts = json.loads((dest / "prompts.json").read_text())
    from biosim_operator.experiment_record import PACK_VERSION

    assert prompts["pack_version"] == PACK_VERSION
    assert "read_sband" in prompts["start_prompt"]


def test_biosim_mcp_missing_detects_cursor_plugin_fallback():
    assert biosim_mcp_missing(
        'MCP server "biosim" not found. Available servers: plugin-provider_cloud-provider_cloud'
    )
    assert biosim_mcp_missing(
        r'{"error": "MCP server \"biosim\" not found. Available servers: plugin-provider_cloud"}'
    )
    assert biosim_mcp_missing('MCP server does not exist: biosim')
    assert biosim_mcp_missing('MCP server "eclss" not found. Available servers: plugin-provider_cloud')
    assert not biosim_mcp_missing('{"type":"tool_call","name":"read_sband"}')


def test_assert_cursor_eclss_rejects_connection_failed(monkeypatch, tmp_path: Path):
    from biosim_operator.cli_episode import assert_cursor_biosim_configured

    monkeypatch.setattr(
        "biosim_operator.cli_episode.cursor_agent_bin",
        lambda: "/usr/bin/true",
    )

    class Fake:
        stdout = "eclss: Error: Connection failed\n"
        stderr = ""

    monkeypatch.setattr(
        "biosim_operator.cli_episode.subprocess.run",
        lambda *a, **k: Fake(),
    )
    (tmp_path / ".cursor").mkdir()
    try:
        assert_cursor_biosim_configured(tmp_path)
    except RuntimeError as exc:
        assert "Connection failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
