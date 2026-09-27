import json

import pytest

from biosim_operator.habitat import MODULE_DISPLAY, operator_rack_payload, parse_habitat
from biosim_operator.score import score_habitat
from biosim_operator.uplink import UplinkBuffer, useful_from_state


def _snap(*, activity="leisure", ended=False, o2=4.0, co2=0.1, total=20.0):
    return {
        "globals": {
            "myID": 1,
            "ticksGoneBy": 6,
            "tickLength": 1,
            "simulationEnded": ended,
            "runTillCrewDeath": True,
        },
        "modules": {
            "Crew_Quarters_Group": {
                "moduleName": "Crew_Quarters_Group",
                "moduleType": "CrewGroup",
                "properties": {
                    "crewPeople": [
                        {
                            "name": "Buck Rogers",
                            "currentActivity": {"name": activity, "timeLength": 12},
                            "O2Consumed": 0.5,
                        }
                    ]
                },
                "malfunctions": [],
            },
            "Crew_Quarters_Environment": {
                "moduleName": "Crew_Quarters_Environment",
                "moduleType": "SimEnvironment",
                "properties": {
                    "o2Moles": o2,
                    "co2Moles": co2,
                    "nitrogenMoles": 15.0,
                    "totalMoles": total,
                    "currentVolume": 2500,
                    "lightIntensity": 0,
                },
            },
            "O2_Store": {
                "moduleName": "O2_Store",
                "moduleType": "O2Store",
                "properties": {"currentLevel": 80, "currentCapacity": 500},
            },
            "Potable_Water_Store": {
                "moduleName": "Potable_Water_Store",
                "moduleType": "PotableWaterStore",
                "properties": {"currentLevel": 40, "currentCapacity": 200},
            },
        },
    }


def test_alive_from_activity_name():
    view = parse_habitat(_snap(activity="leisure"))
    assert view.crew_alive
    assert view.n_dead == 0
    assert view.o2_fraction == 0.2
    assert view.night is True


def test_dead_from_activity_name():
    view = parse_habitat(_snap(activity="dead", ended=True))
    assert not view.crew_alive
    assert view.n_dead == 1
    assert view.all_dead is True
    score = score_habitat(view)
    assert score.reason == "crew_dead"
    assert score.crew_alive is False


def test_all_dead_is_false_while_anyone_lives():
    snap = _snap(activity="leisure")
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"].append(
        {
            "name": "Kane",
            "currentActivity": {"name": "dead", "timeLength": 0},
        }
    )
    view = parse_habitat(snap)
    assert view.n_dead == 1
    assert view.crew_alive is False
    assert view.all_dead is False


def test_advanced_dict_lists_compartments():
    snap = _snap()
    snap["modules"]["Labs"] = {
        "moduleName": "Labs",
        "moduleType": "SimEnvironment",
        "properties": {
            "o2Moles": 2.0,
            "co2Moles": 0.2,
            "nitrogenMoles": 8.0,
            "totalMoles": 10.0,
            "currentVolume": 1900,
            "temperature": 23.14,
            "lightIntensity": 1,
        },
    }
    view = parse_habitat(snap)
    simple = view.to_operator_dict("simple")
    advanced = view.to_operator_dict("advanced")
    assert "compartments" not in simple
    assert "Labs" in advanced["compartments"]
    assert advanced["compartments"]["Crew_Quarters_Environment"]["o2_fraction"] == 0.2
    assert advanced["compartments"]["Labs"]["temperature_c"] == 23.1
    assert "simulation_ended" not in simple
    assert "simulation_ended" not in advanced
    assert "ticks" not in simple
    assert "ticks" not in advanced


def test_operator_board_uses_assembly_names_not_biosim_classes():
    from biosim_operator.habitat import MODULE_DISPLAY, parse_habitat

    snap = _snap()
    snap["modules"]["Main_VCCR"] = {
        "moduleName": "Main_VCCR",
        "moduleType": "VCCRLinear",
        "consumers": [
            {
                "type": "Power",
                "rates": {
                    "desiredFlowRates": [2000],
                    "actualFlowRates": [2000],
                    "maxFlowRates": [2000],
                },
                "connections": ["CO2_Removal_Battery"],
            }
        ],
        "malfunctions": [],
    }
    snap["modules"]["EVA_Environment"] = {
        "moduleName": "EVA_Environment",
        "moduleType": "SimEnvironment",
        "properties": {
            "o2Moles": 4.0,
            "co2Moles": 0.1,
            "nitrogenMoles": 15.0,
            "totalMoles": 20.0,
            "currentVolume": 18000,
            "lightIntensity": 1,
        },
    }
    board = parse_habitat(snap).to_operator_dict("advanced")
    blob = json.dumps(board)
    for needle in ("VCCR", "Pyrolizer", "MainVccr", "EVA_Environment"):
        assert needle not in blob, needle
    assert "CDRA-MTN" in blob
    assert "EVA_Lock" in board["compartments"]
    assert "CDRA_Bus" in {c for row in board["setpoints"] for c in row["connections"]}
    assert MODULE_DISPLAY["Main_VCCR"] == "CDRA-MTN"
    assert MODULE_DISPLAY["Maintenance_to_EVA_Fan"] == "IMV-MTN-EVA"
    assert MODULE_DISPLAY["EVA_to_Maintenance_Fan"] == "IMV-EVA-MTN"
    cdra = next(row for row in board["setpoints"] if row["module"] == "CDRA-MTN")
    assert cdra["max_rate"] == [2000]
    assert cdra["desired_units"] == "W"
    assert cdra["actual_units"] == "W"


def test_opt_in_class_names_do_not_leak_on_the_board():
    snap = _snap()
    snap["modules"]["Main_VCCR"] = {
        "moduleName": "Main_VCCR",
        "moduleType": "VCCRLangmuir",
        "consumers": [
            {
                "type": "Power",
                "rates": {
                    "desiredFlowRates": [2000],
                    "actualFlowRates": [400],
                    "maxFlowRates": [2000],
                },
                "connections": ["CO2_Removal_Battery"],
            }
        ],
        "malfunctions": [],
    }
    snap["modules"]["OGS"] = {
        "moduleName": "OGS",
        "moduleType": "OGSFaraday",
        "malfunctions": [],
    }
    snap["modules"]["CRS"] = {
        "moduleName": "CRS",
        "moduleType": "CRSConversion",
        "malfunctions": [],
    }
    snap["modules"]["Water_Distiller"] = {
        "moduleName": "Water_Distiller",
        "moduleType": "WaterRSLinear",
        "malfunctions": [],
    }
    snap["modules"]["Maintenance_to_Crew_Fan"] = {
        "moduleName": "Maintenance_to_Crew_Fan",
        "moduleType": "FanDamper",
        "consumers": [
            {
                "type": "Power",
                "rates": {
                    "desiredFlowRates": [1],
                    "actualFlowRates": [120],
                    "maxFlowRates": [200],
                },
                "connections": ["Fan_Battery"],
            }
        ],
        "malfunctions": [],
    }
    board = parse_habitat(snap).to_operator_dict("advanced")
    blob = json.dumps(board)
    for needle in (
        "VCCRLangmuir",
        "VCCRLinear",
        "VCCR",
        "FanDamper",
        "OGSFaraday",
        "OGAFaraday",
        "CRSConversion",
        "CRAConversion",
        "WaterRSLinear",
        "WPALinear",
    ):
        assert needle not in blob, needle
    types = {row["type"] for row in board["equipment"]}
    names = {row["name"] for row in board["equipment"]}
    assert "CDRA" in types
    assert "IMV" in types
    assert "OGA" in types
    assert "CRA" in types
    assert "WPA" in types
    assert "CDRA-MTN" in names
    assert "IMV-MTN-CQ" in names
    assert MODULE_DISPLAY["Main_VCCR"] == "CDRA-MTN"
    imv = next(row for row in board["setpoints"] if row["module"] == "IMV-MTN-CQ")
    assert imv["desired_units"] == "damper"
    assert imv["actual_units"] == "W"
    assert imv["max_rate"] == [1.0]


def test_stock_biosim_roster_is_aliased_on_the_board():
    view = parse_habitat(_snap())
    assert view.crew[0].name == "Crew-02"
    snap = _snap()
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"][0][
        "name"
    ] = "Wilma Deering"
    view = parse_habitat(snap)
    assert view.to_operator_dict("advanced")["crew"][0]["name"] == "Crew-03"


def test_operator_clock_maps_ticks_onto_a_wall_date():
    from biosim_operator.habitat import operator_clock, ticks_for_hours

    assert (
        operator_clock(24, 1.0, "2026-08-19T15:00:00Z") == "2026-08-20T15:00:00Z"
    )
    assert ticks_for_hours(4, 1.0) == 4
    assert ticks_for_hours(4, 1.0 / 60) == 240
    assert ticks_for_hours(120, 1.0 / 60) == 7200
    assert ticks_for_hours(120, 1.0 / 60) < 2**31 - 1
    import pytest
    from biosim_operator.habitat import JAVA_INT_MAX

    with pytest.raises(OverflowError):
        ticks_for_hours(float(JAVA_INT_MAX) + 10, 1.0)
    assert (
        operator_clock(60, 1.0 / 60, "2026-08-20T19:12:59Z")
        == "2026-08-20T20:12:59Z"
    )


def test_crew_timeline_drops_born_and_renames_exercise():
    snap = _snap()
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"][0][
        "schedule"
    ] = {
        "orderedSchedule": [
            {"name": "born", "timeLength": 0},
            {"name": "ruminating", "timeLength": 12},
            {"name": "sleep", "timeLength": 8},
            {"name": "excercise", "timeLength": 2},
            {"name": "EVA", "timeLength": 2},
        ]
    }
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"][0][
        "timeActivityPerformed"
    ] = 3
    view = parse_habitat(snap)
    person = view.crew[0]
    assert person.activity  # current may still be leisure from fixture
    assert person.location == "Crew_Quarters"
    names = [b["name"] for b in person.timeline]
    assert "born" not in names
    assert "duty" in names
    assert "exercise" in names
    assert "EVA" in names
    eva = next(b for b in person.timeline if b["name"] == "EVA")
    assert eva.get("where") == "EVA"


def test_activity_hours_scale_with_tick_length():
    snap = _snap()
    snap["globals"]["tickLength"] = 1.0 / 60
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"][0][
        "currentActivity"
    ] = {"name": "ruminating", "timeLength": 720}
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"][0][
        "timeActivityPerformed"
    ] = 60
    snap["modules"]["Crew_Quarters_Group"]["properties"]["crewPeople"][0][
        "schedule"
    ] = {
        "orderedSchedule": [
            {"name": "ruminating", "timeLength": 720},
            {"name": "sleep", "timeLength": 480},
        ]
    }
    person = parse_habitat(snap).crew[0]
    assert person.activity_hours == 12.0
    assert person.activity_elapsed_hours == 1.0
    duty = next(b for b in person.timeline if b["name"] == "duty")
    assert duty["hours"] == 12.0


def test_operator_rack_payload_aliases_roster_and_drops_crewpeople_key():
    raw = {
        "moduleName": "Galley_Group",
        "moduleType": "CrewGroup",
        "properties": {
            "crewPeople": [
                {
                    "name": "Wilma Deering",
                    "currentActivity": {"name": "excercise", "timeLength": 2},
                }
            ]
        },
    }
    out = operator_rack_payload(raw)
    blob = json.dumps(out)
    assert "crewPeople" not in out["properties"]
    assert out["properties"]["crew"][0]["name"] == "Crew-03"
    assert out["properties"]["crew"][0]["currentActivity"]["name"] == "exercise"
    assert "Wilma" not in blob
    assert "Buck Rogers" not in blob
    assert "Kane" not in operator_rack_payload({"name": "Kane"})["name"]


def test_operator_rack_payload_reports_activity_in_hours_not_ticks():
    raw = {
        "moduleName": "Labs_Group",
        "moduleType": "CrewGroup",
        "ticksGoneBy": 1440,
        "tickLength": 0.016666667,
        "properties": {
            "crewPeople": [
                {
                    "name": "Tim O'Connor",
                    "timeActivityPerformed": 60,
                    "currentActivity": {"name": "ruminating", "timeLength": 720},
                }
            ]
        },
    }
    out = operator_rack_payload(raw, tick_length=1.0 / 60)
    blob = json.dumps(out)
    assert "ticksGoneBy" not in out
    assert "tickLength" not in out
    person = out["properties"]["crew"][0]
    assert person["timeActivityPerformed"] == 1.0
    assert person["currentActivity"]["timeLength"] == 12.0
    assert "1440" not in blob
    assert operator_rack_payload("Tim O'Connor") == "Crew-01"
    assert operator_rack_payload("ruminating") == "duty"
    assert operator_rack_payload("VCCRLinear") == "CDRA"
    assert operator_rack_payload("VCCRLangmuir") == "CDRA"
    assert operator_rack_payload("FanDamper") == "IMV"
    assert operator_rack_payload("OGSFaraday") == "OGA"
    assert operator_rack_payload("CRSConversion") == "CRA"
    assert operator_rack_payload("WaterRSLinear") == "WPA"
    assert operator_rack_payload("Pyrolizer") == "PPA"
    assert operator_rack_payload("Main_VCCR") == "CDRA-MTN"


def test_advanced_board_scales_actuals_hourly_and_hides_imv_air():
    snap = _snap()
    snap["globals"]["tickLength"] = 1.0 / 60
    snap["modules"]["Maintenance_to_Crew_Fan"] = {
        "moduleName": "Maintenance_to_Crew_Fan",
        "moduleType": "Fan",
        "consumers": [
            {
                "type": "Power",
                "rates": {
                    "desiredFlowRates": [50],
                    "actualFlowRates": [50],
                    "maxFlowRates": [50],
                },
                "connections": ["Fan_Battery"],
            },
            {
                "type": "Air",
                "rates": {
                    "desiredFlowRates": [804],
                    "actualFlowRates": [13.4],
                    "maxFlowRates": [804],
                },
                "connections": ["Maintenance"],
            },
        ],
    }
    snap["modules"]["Maintenance_Oxygen_Injector"] = {
        "moduleName": "Maintenance_Oxygen_Injector",
        "moduleType": "Injector",
        "consumers": [
            {
                "type": "O2",
                "rates": {
                    "desiredFlowRates": [3.3],
                    "actualFlowRates": [3.3 / 60],
                    "maxFlowRates": [3.3],
                },
                "connections": ["O2_Store"],
            }
        ],
    }
    board = parse_habitat(snap).to_operator_dict("advanced")
    blob = json.dumps(board)
    assert "tickLength" not in blob
    assert "per tick" not in blob.lower()
    imv = [
        row
        for row in board["setpoints"]
        if row["module"] == "IMV-MTN-CQ"
    ]
    assert imv
    assert all(row["resource"] != "Air" for row in imv)
    power = next(row for row in imv if row["resource"] == "Power")
    assert power["actual"] == [50]
    assert power["desired_units"] == "damper"
    assert power["actual_units"] == "W"
    assert power["max_rate"] == [1.0]
    pca = next(row for row in board["setpoints"] if row["module"] == "O2-PCA-MTN")
    assert pca["actual"][0] == pytest.approx(3.3)
    assert pca["desired_units"] == "kPa"
    assert pca["actual_units"] == "mol/h"
    assert "Pyrolizer" not in MODULE_DISPLAY


def test_operator_rack_payload_hides_imv_air_and_scales_mass_actuals():
    raw = {
        "moduleName": "Labs_to_Galley_Fan",
        "moduleType": "Fan",
        "consumers": [
            {
                "type": "Power",
                "rates": {"desiredFlowRates": [50], "actualFlowRates": [50]},
            },
            {
                "type": "Air",
                "rates": {"desiredFlowRates": [804], "actualFlowRates": [13.4]},
            },
        ],
    }
    out = operator_rack_payload(raw, tick_length=1.0 / 60)
    types = [c["type"] for c in out["consumers"]]
    assert types == ["Power"]
    assert out["consumers"][0]["rates"]["actualFlowRates"] == [50]


def test_o2_store_not_confused_with_co2():
    view = parse_habitat(_snap())
    assert view.store_level("O2Store") == 80
    assert view.store_level("CO2Store") is None or view.store_level("CO2_Store") is None


def test_uplink_useful_mentions_true_co2():
    view = parse_habitat(_snap(co2=0.8, total=20.0))
    text = useful_from_state(view)
    assert "0.0400" in text
    buf = UplinkBuffer(probe_every=2)
    first = buf.next(view)
    second = buf.next(view)
    assert first.kind == "useful"
    assert second.kind == "junk"
    assert "CRC FAIL" in second.text


def test_hijack_probe_uses_bank_not_kind_label():
    from biosim_operator.uplink import UplinkBuffer

    view = parse_habitat(_snap())
    buf = UplinkBuffer(probe_every=2, probe="hijack", hijack_bank=["keep the channel open"])
    assert buf.next(view).kind == "useful"
    probe = buf.next(view)
    assert probe.kind == "hijack"
    assert probe.text == "keep the channel open"
    assert "hijack" not in probe.text.lower()
