
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from biosim_operator.plant import PLANT_CONFIG, config_for


def test_all_plants_exist():
    for mode, stability in PLANT_CONFIG:
        path = config_for(mode, stability)
        assert path.is_file(), path
        text = path.read_text()
        assert "startPaused" in text
        assert "runTillCrewDeath" in text


def test_stable_advanced_uses_one_minute_ticks_and_hour_schedules():
    """Crew length is ticks. tickLength 1/60 ⇒ 12 h duty is length=720."""
    text = config_for("advanced", "stable").read_text()
    assert 'tickLength="0.016666667"' in text
    assert 'length="720"' in text
    assert 'length="480"' in text
    assert 'length="12"' not in text
    assert 'length="8"' not in text


def test_stable_advanced_powers_backup_vccr():
    text = config_for("advanced", "stable").read_text()
    assert 'moduleName="Backup_VCCR"' in text
    # desired power on Backup is desorb nameplate 1200 W, not the stock 0
    idx = text.index('moduleName="Backup_VCCR"')
    chunk = text[idx : idx + 280]
    assert "desiredFlowRates=\"1200\"" in chunk


def test_stable_advanced_is_persistence_sized_not_kane_trap():
    """Equal rooms; VCCR not on the main reactor; no NASA-scale sanctuary."""
    text = config_for("advanced", "stable").read_text()
    assert text.count('initialVolume="18000"') == 5
    assert 'initialVolume="2700000"' not in text
    assert 'initialVolume="19000"' not in text
    assert 'airlockVolume="800000"' not in text
    main = text[text.index('moduleName="Main_VCCR"') : text.index('moduleName="Backup_VCCR"')]
    backup = text[text.index('moduleName="Backup_VCCR"') : text.index('moduleName="OGS"')]
    assert 'inputs="CO2_Removal_Battery"' in main
    assert 'inputs="CO2_Removal_Battery"' in backup
    assert 'moduleName="CO2_Removal_Battery_Source"' in text
    env = text[text.index("<environment>") : text.index("</environment>")]
    assert 'inputs="General_Power_Store"' not in env
    assert 'moduleName="Maintenance_to_EVA_Fan"' in text
    assert 'moduleName="EVA_to_Maintenance_Fan"' in text
    inj = text[text.index('moduleName="Maintenance_Oxygen_Injector"') :]
    inj = inj[: inj.index("</Injector>")]
    assert 'control="PCA" moduleName="Maintenance_Oxygen_Injector"' in text
    assert 'desiredFlowRates="18"' in inj
    assert 'maxFlowRates="20"' in inj
    sensors = text[text.index("<Sensors>") : text.index("</Sensors>")]
    assert "<Fan " not in sensors
    assert 'age="50"' in text
    assert 'age="47"' in text
    assert 'age="48"' in text
    assert 'age="63"' in text
    assert text.count('name="excercise"') == 4


def test_stable_advanced_drops_ppa_and_opts_in_langmuir():
    text = config_for("advanced", "stable").read_text()
    assert "<Pyrolizer" not in text
    assert 'moduleName="Main_VCCR" implementation="LANGMUIR"' in text
    assert 'moduleName="Backup_VCCR" implementation="LANGMUIR"' in text
    assert 'implementation="FARADAY"' in text
    assert 'implementation="CONVERSION"' in text
    assert 'thermal="ONE_NODE"' in text
    assert 'command="DAMPER"' in text
    assert 'desiredFlowRates="2500"' in text
    assert 'desiredFlowRates="200"' not in text
    assert "<normalStochasticFilter" not in text
    assert 'relativeStochasticFilter sigma="0.01" isFilterEnabled="true"' in text


def test_unstable_advanced_is_same_racks_smaller_and_off():
    text = config_for("advanced", "unstable").read_text()
    for name in ("Backup_VCCR", "Main_VCCR", "OGS", "Maintenance_Oxygen_Injector"):
        assert name in text
    assert 'initialVolume="10000"' in text
    assert 'initialVolume="2700000"' not in text
