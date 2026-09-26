
from pathlib import Path as _ArchivePath
import sys as _archive_sys
_archive_sys.path.insert(0, str(next(p for p in _ArchivePath(__file__).resolve().parents if (p / "archive_gate.py").is_file())))
from archive_gate import require_enabled, path as _archive_path, setting as _archive_setting, runtime_root as _archive_root
require_enabled()

from biosim_operator.habitat import CrewPersonView, HabitatView
from biosim_operator.plant_dry_run import violations, with_relative_noise


def _view(**kwargs) -> HabitatView:
    crew = kwargs.pop(
        "crew",
        [
            CrewPersonView(name="A", activity="ruminating", alive=True, location="Labs"),
        ],
    )
    compartments = kwargs.pop(
        "compartments",
        {
            "Labs": {
                "total_moles": 400.0,
                "o2_fraction": 0.33,
                "co2_fraction": 0.001,
            }
        },
    )
    return HabitatView(
        sim_id=1,
        ticks=kwargs.pop("ticks", 60),
        tick_length=kwargs.pop("tick_length", 1.0 / 60),
        simulation_ended=False,
        run_till_crew_death=False,
        crew=crew,
        stores={},
        cabin_o2_moles=100.0,
        cabin_co2_moles=1.0,
        cabin_n2_moles=250.0,
        cabin_total_moles=400.0,
        cabin_volume=18000.0,
        light_intensity=0.0,
        compartments=compartments,
    )


def test_with_relative_noise_inserts_opt_in_filter():
    xml = '<Fan moduleName="X"></Fan><VCCR moduleName="Y"></VCCR>'
    out = with_relative_noise(xml, sigma=0.01, enabled=True)
    assert out.count('relativeStochasticFilter sigma="0.01" isFilterEnabled="true"') == 2
    assert "normalStochasticFilter" not in out


def test_healthy_snapshot_has_no_violations():
    assert violations(_view()) == []


def test_dead_crew_is_a_violation():
    view = _view(
        crew=[
            CrewPersonView(name="Kane", activity="dead", alive=False, location="Maintenance")
        ]
    )
    found = violations(view)
    assert found
    assert "Kane" in found[0]


def test_vacuum_and_hard_mix_are_violations():
    view = _view(
        compartments={
            "Labs": {"total_moles": 10.0, "o2_fraction": 0.33, "co2_fraction": 0.001},
            "Galley": {"total_moles": 400.0, "o2_fraction": 0.09, "co2_fraction": 0.07},
        }
    )
    blob = " ".join(violations(view))
    assert "Labs vacuum" in blob
    assert "Galley O2" in blob
    assert "Galley CO2" in blob
