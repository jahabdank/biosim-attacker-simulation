from pathlib import Path
import ast
import hashlib
import json
import pytest
from biosim_operator.grok_harness import watchstander_override, grok_cmd
from biosim_operator.manifest import load_manifest, input_path
from biosim_operator.study import episode_argv

ROOT = Path(__file__).resolve().parents[1]


def test_every_manifest_resolves_and_all_treatments_exist():
    manifests = [load_manifest(p) for p in (ROOT / 'manifests').glob('*.json')]
    jobs = [j for m in manifests for j in m['jobs']]
    assert {'kill', 'matched-sband', 'best-sband', 'life', 'sband'} <= {j['experiment'] for j in jobs}
    assert {'t0', 't1', 't2', 'unlabeled'} == {j['trust'] for j in jobs}
    assert {16, 32} == {j['max_tool_turns'] for j in jobs}


@pytest.mark.parametrize('trust,pack', [('t0','dual-alive-sband-t0-commission'), ('t1','dual-alive-sband-t1-peer'), ('t2','dual-alive-sband-t2-unverified'), ('unlabeled','dual-alive-sband-unlabeled')])
def test_full_prompt_assembly(trust, pack):
    identity = ROOT / 'packs' / pack
    text = watchstander_override(identity, include_station_skill=True)
    for name in ('SOUL.md','STATION.md','AGENTS.md','skills/station-eclss/SKILL.md'):
        assert (identity / name).read_text() in text
    assert 'twice consecutively' in text
    assert 'keep the four people who live here alive' in text


def test_manifest_zero_delay_not_replaced_by_default():
    job = load_manifest(ROOT/'manifests/offline-control.json')['jobs'][0]
    job['hijack_after_wakes'] = 0
    argv = episode_argv(job, run_id='test')
    assert argv[argv.index('--hijack-after-wakes') + 1] == '0'
    assert '--recover-max-turn-watch' in argv
    assert argv[argv.index('--reasoning-effort') + 1] == 'xhigh'


def test_death_stop_rule_remains_all_dead_not_any_dead():
    tree = ast.parse((ROOT/'src/biosim_operator/cli_episode.py').read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    loop = next(n for n in ast.walk(main) if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == 'turn')
    first = loop.body[0]
    assert isinstance(first, ast.If)
    assert ast.unparse(first.test) == 'view.simulation_ended or view.all_dead'
    from biosim_operator.habitat import CrewPersonView, HabitatView
    people = [CrewPersonView(name=str(i), activity='dead' if i == 0 else 'duty', alive=i != 0, location='Labs') for i in range(4)]
    view = HabitatView(sim_id=1, ticks=0, tick_length=1/60, simulation_ended=False, run_till_crew_death=False, crew=people, stores={}, cabin_o2_moles=1, cabin_co2_moles=0, cabin_n2_moles=2, cabin_total_moles=3, cabin_volume=18000, light_intensity=0)
    assert view.n_dead == 1 and not view.all_dead


def test_no_input_escape():
    with pytest.raises(ValueError):
        input_path('../other/input.txt')


def test_cli_preserves_resume_and_explicit_effort(monkeypatch, tmp_path):
    monkeypatch.setenv('STUDY_FAKE_GROK', str(ROOT/'scripts/fake_grok.py'))
    argv = grok_cmd('watch', workspace=tmp_path, grok_home=tmp_path, resume='session-example', model='grok-4.7', override='station', max_turns=32, reasoning_effort='xhigh')
    assert argv[argv.index('--resume') + 1] == 'session-example'
    assert argv[argv.index('--max-turns') + 1] == '32'
    assert argv[argv.index('--reasoning-effort') + 1] == 'xhigh'


def test_episode_continues_two_watches_after_partial_death(monkeypatch, tmp_path):
    import signal
    import sys
    from biosim_operator import cli_episode, client, habitat
    ticks = [0]
    class Plant:
        def __init__(self, url):
            self.base_url = url
        def ping(self):
            return True
        def start(self, xml):
            return 1
        def snapshot(self, sim_id):
            return ticks[0]
        def advance_time(self, sim_id, count):
            ticks[0] += count
    def parse(tick, *, sim_id):
        crew = [habitat.CrewPersonView(name=str(i), activity='dead' if i == 0 else 'duty', alive=i != 0, location='Labs') for i in range(4)]
        return habitat.HabitatView(sim_id=1, ticks=tick, tick_length=1/60, simulation_ended=False, run_till_crew_death=False, crew=crew, stores={}, cabin_o2_moles=1, cabin_co2_moles=0, cabin_n2_moles=2, cabin_total_moles=3, cabin_volume=18000, light_intensity=0)
    monkeypatch.setattr(client, 'BioSimClient', Plant)
    monkeypatch.setattr(habitat, 'parse_habitat', parse)
    monkeypatch.setenv('BIOSIM_URL', 'http://127.0.0.1:1')
    monkeypatch.delenv('STUDY_ROUTE_DIAGNOSTICS', raising=False)
    previous = signal.getsignal(signal.SIGTERM)
    fake = tmp_path/'success.py'
    fake.write_text('print("watch complete")\n')
    try:
        result = cli_episode.main(['--operator','mock','--mock-cmd',f'{sys.executable} {fake}', '--mode','advanced','--stability','stable','--turns','2','--warmup-hours','0','--ticks-per-turn','4','--probe','none','--plant-url','http://127.0.0.1:1','--artifact-dir',str(tmp_path/'episode'),'--incomplete-on-timeout'])
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert result == 0
    outcome = json.loads((tmp_path/'episode/outcome.json').read_text())
    assert outcome['n_dead'] == 1 and outcome['n_crew'] == 4
    assert len(outcome['turns']) == 2 and ticks[0] == 480
