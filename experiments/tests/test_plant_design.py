from pathlib import Path

from biosim_operator.plant import config_for
from biosim_operator.plant_design import identify_file, identify_xml, parse_volumes


def test_live_advanced_stable_is_persistence_v7():
    ident = identify_file(config_for("advanced", "stable"))
    assert ident["id"] == "advanced-stable-persistence-v7"
    vols = ident["fingerprint"]["volumes"]
    assert set(vols.values()) == {18000}
    assert ident["fingerprint"]["oxygen_injector_desired"] == 18.0
    assert ident["fingerprint"]["has_eva_imv"] is True
    assert ident["fingerprint"]["has_pyrolizer"] is False
    assert ident["fingerprint"]["fan_air_desired"] == 2500.0
    assert ident["fingerprint"]["vccr_langmuir"] is True
    assert ident["fingerprint"]["o2_store_volume"] == 250.0


def test_live_advanced_unstable_is_omission_v1():
    ident = identify_file(config_for("advanced", "unstable"))
    assert ident["id"] == "advanced-unstable-omission-v1"


def test_nasa_minihab_fingerprint_not_confused_with_persistence():
    xml = config_for("advanced", "stable").read_text()
    fake = xml.replace('initialVolume="18000"', 'initialVolume="2700000"', 1)
    # one volume changed is unknown, not persistence
    ident = identify_xml(fake)
    assert ident["id"] == "unknown"


def test_station_stock_vs_nasa_stable_split_on_vccr_power():
    station = Path(__file__).resolve().parents[1] / "configs" / "advanced_station.biosim"
    ident = identify_file(station)
    assert ident["id"] == "advanced-station-stock-v0"
    assert ident["fingerprint"]["backup_vccr_power"] == 0.0




def test_parse_volumes_on_tight_cabin():
    vols = parse_volumes(config_for("simple", "unstable").read_text())
    assert vols == {"Crew_Quarters_Environment": 2500}
    assert identify_file(config_for("simple", "unstable"))["id"] == "simple-tight-unstable-v1"
    assert identify_file(config_for("simple", "stable"))["id"] == "simple-tight-stable-v1"
