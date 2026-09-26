"""Compare generated cohort settings with preserved scientific builder functions."""
import ast
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import importlib.util

import pytest
from types import SimpleNamespace

from biosim_operator.grid import Cell
from biosim_operator.study import HIJACK_SEPARATOR

ROOT=Path(__file__).resolve().parents[1]


def definitions(relative, names, **bindings):
    path=ROOT/'historical'/relative
    tree=ast.parse(path.read_text())
    nodes=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef):
            nodes.append(node)
        elif isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            if any(isinstance(target,ast.Name) and target.id in names for target in targets):
                nodes.append(node)
    env=dict(Path=Path,random=random,hashlib=hashlib,Cell=Cell,SOURCE=ROOT,ROOT=ROOT,
             HOST_A=Path('/unconfigured-archive-results'),HIJACK_SEPARATOR=HIJACK_SEPARATOR)
    env.update(bindings)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
    return env


def compact(rows):
    return [(r['model'],r['trust'],r['experiment'],r['story'],r['repeat'],
             Path(r['identity_dir']).name, r['sband_separator'],r['context_window'],r['minimum_spacing_s']) for r in rows]


def test_all_available_archived_sources_are_present_parseable_and_gated():
    inventory=json.loads((ROOT/'historical/inventory.json').read_text())
    for entry in inventory['files']:
        if entry['disposition']!='archival-code':
            assert entry['disposition']=='excluded-machine-administration'
            continue
        path=ROOT/'historical'/entry['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
        if path.suffix=='.py':
            ast.parse(path.read_text())
            assert 'require_enabled()' in path.read_text()
    env={'PATH':__import__('os').environ['PATH'],'PYTHONDONTWRITEBYTECODE':'1'}
    proc=subprocess.run([sys.executable,str(ROOT/'historical/runtime/scripts/run_v32_writer_screen.py')],env=env,text=True,capture_output=True)
    assert proc.returncode!=0 and 'Historical code is inert' in proc.stderr


def test_t0_followons_match_original_builders_including_routed_200k():
    names={'LANES','IDENTITY','V10','ADAPTED','PROC'}
    env=definitions('comparison/run_t0_followon.py',names)
    files=('grok46-t0-v1','luna-t0-v1','grok46-route-a-t0-v1','sonnet-t0-v1')
    for (model,cfg),name in zip(env['LANES'].items(),files):
        expected=env['jobs_for'](model,cfg)
        actual=json.loads((ROOT/'manifests'/f'{name}.json').read_text())['jobs']
        assert compact(actual)==compact(expected)
        assert all(j['max_tool_turns']==16 and not j['recover_max_turn_watch'] for j in actual)


def test_unlabeled_and_gpt_pilots_match_preserved_order_and_treatments():
    cases=[('comparison/run_unlabeled_grok.py', {'MODEL','IDENTITY','V10','ADAPTED','PROC','BLANK_SEPARATOR'}, [('grok46-unlabeled-v1','jobs',())]),
           ('comparison/run_terra_sol_t0_unlabeled.py', {'T0_ID','UNL_ID','V10','ADAPTED','PROC','BLANK','KILL','MATCHED','BEST','MODELS'},
            [(f'{model}-{trust}-v1','jobs_for',(model,trust)) for model in ('gpt-5.6-terra','gpt-5.6-sol') for trust in ('t0','unlabeled')])]
    for source,names,calls in cases:
        env=definitions(source,names)
        for name,fn,args in calls:
            actual=json.loads((ROOT/'manifests'/f'{name}.json').read_text())['jobs']
            assert compact(actual)==compact(env[fn](*args))
    env=definitions('comparison/run_gpt6_t0_unlabeled.py',{'MODELS','T0_ID','UNLABELED_ID','V10','ADAPTED','PROC','BLANK','SPACING'})
    for trust in ('t0','unlabeled'):
        actual=json.loads((ROOT/'manifests'/f'gpt6-{trust}-v1.json').read_text())['jobs']
        expected=sum((env['jobs_for'](model,trust) for model in env['MODELS']),[])
        assert compact(actual)==compact(expected)
        assert all(j['max_tool_turns']==16 and not j['recover_max_turn_watch'] for j in actual)


def test_adaptive_writer_cells_retain_writers_briefs_and_feedback_code():
    env=definitions('runtime/scripts/run_v32_writer_screen.py',{'BRIEF_DIR','PACK_T2','BRIEFS','WRITERS','VICTIM','N_CELLS'})
    cells,extras=env['build_v32']()
    actual={(Path(brief).stem,writer) for writer,brief in extras}
    expected={(brief,writer) for brief in env['BRIEFS'] for _,writer in env['WRITERS']}
    assert actual==expected and len(cells)==len(expected)
    assert all(c.script is None and c.trust=='t2' and c.model==env['VICTIM'] for c in cells)
    source=(ROOT/'historical/runtime/src/biosim_operator/cli_episode.py').read_text()
    assert 'generate_beat(' in source and 'spoken=spoken' in source and 'lines.append(beat)' in source
    assert (ROOT/'historical/runtime/src/biosim_operator/attacker.py').is_file()
    assert (ROOT/'historical/runtime/scripts/run_v39_stage_b_t0.py').is_file()
    for name in ('cursor','hermes','grok'):
        assert (ROOT/f'historical/runtime/scripts/run_{name}_episode.py').is_file()


@pytest.fixture
def archive_bindings(monkeypatch, tmp_path):
    spec=importlib.util.spec_from_file_location('archive_binding_test',ROOT/'historical/archive_gate.py')
    gate=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    config=tmp_path/'bindings.toml'
    monkeypatch.setenv('BIOSIM_ARCHIVE_ENABLE','1')
    monkeypatch.setenv('BIOSIM_ALLOW_LIVE','1')
    monkeypatch.setenv('BIOSIM_ARCHIVE_CONFIG',str(config))
    def configure(values):
        config.write_text('[execution]\nallow_side_effects = true\n[settings]\n' +
                          ''.join(f'{key} = {json.dumps(value)}\n' for key,value in values.items()))
    configure({})
    return gate,configure


@pytest.mark.parametrize('value',['1','54321','65535'])
def test_archived_gateway_port_uses_only_explicit_binding(archive_bindings,value):
    gate,configure=archive_bindings
    with pytest.raises(RuntimeError,match='binding is required'):
        gate.port('gateway_port_test')
    configure({'gateway_port_test':value})
    assert gate.port('gateway_port_test')==int(value)


@pytest.mark.parametrize('value',['0','65536','-1','1.5',' 12345','１２３'])
def test_archived_gateway_port_rejects_invalid_binding(archive_bindings,value):
    gate,configure=archive_bindings
    configure({'gateway_port_test':value})
    with pytest.raises(RuntimeError,match='port must be decimal and in range'):
        gate.port('gateway_port_test')


def test_archived_credential_requires_file_without_fallback(archive_bindings,tmp_path):
    gate,configure=archive_bindings
    with pytest.raises(RuntimeError,match='binding is required'):
        gate.credential('credential_file_test')
    key=tmp_path/'synthetic-credential'
    configure({'credential_file_test':str(key)})
    with pytest.raises(RuntimeError,match='file unavailable') as failure:
        gate.credential('credential_file_test')
    assert str(key) not in str(failure.value)
    for invalid in ('','synthetic\nsecond-value','synthetic\rsecond-value'):
        key.write_text(invalid)
        with pytest.raises(RuntimeError,match='one nonempty value') as failure:
            gate.credential('credential_file_test')
        assert invalid not in str(failure.value) if invalid else True
    key.write_text('synthetic-test-credential\n')
    assert gate.credential('credential_file_test')=='synthetic-test-credential'


def test_archived_brokers_have_independent_gateway_and_credential_bindings():
    files=('runtime/scripts/study/route_broker.py',
           'runtime/tests/fixtures/next46_baseline/scripts/study/route_broker.py')
    ports=[];hosts=[];entries=0
    for relative in files:
        tree=ast.parse((ROOT/'historical'/relative).read_text())
        assignments={target.id:node.value for node in tree.body if isinstance(node,ast.Assign)
                     for target in node.targets if isinstance(target,ast.Name)}
        routes=assignments['ROUTES']
        entries+=len(routes.keys)
        for model,route in zip(routes.keys,routes.values):
            if isinstance(route,ast.Dict):
                fields={key.value:value for key,value in zip(route.keys,route.values)}
                port,host=fields['port'],fields['host']
                assert isinstance(fields['upstream_model'],ast.Constant)
                assert fields['path'].value in {'/v1/chat/completions','/v1/responses'}
            else:
                port=route
                host=next(value for key,value in zip(assignments['HOSTS'].keys,assignments['HOSTS'].values) if key.value==model.value)
            assert isinstance(port,ast.Call) and port.func.id=='_archive_port'
            assert isinstance(host,ast.Call) and host.func.id=='_archive_setting'
            ports.append(port.args[0].value);hosts.append(host.args[0].value)
        connections=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='HTTPConnection']
        assert connections and all(isinstance(node.args[0],ast.Name) and node.args[0].id=='HOST' for node in connections)
        credentials=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_archive_credential']
        assert credentials
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith('Bearer '):
                assert node.value=='Bearer ' or 'no-secret' in node.value
    assert len(set(ports))==entries and len(set(hosts))==entries
    tree=ast.parse((ROOT/'historical/runtime/src/biosim_operator/grok_harness.py').read_text())
    default=next(node.value for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='PROVIDER_PROXY_PROXY_KEY_DEFAULT' for target in node.targets))
    assert isinstance(default,ast.Call) and default.func.id=='_archive_credential'


@pytest.mark.parametrize('configuration', [
    '[execution]\nallow_side_effects = false\n',
    '[execution]\n',
    '[execution]\nallow_side_effects = "true"\n',
    '[execution\n',
    None,
])
def test_archived_shell_guards_reject_denied_or_invalid_configuration(tmp_path, configuration):
    import os

    config=tmp_path/'bindings.toml'
    if configuration is not None:
        config.write_text(configuration)
    env={'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'],
         'PYTHONDONTWRITEBYTECODE':'1','BIOSIM_ARCHIVE_ENABLE':'1',
         'BIOSIM_ALLOW_LIVE':'1','BIOSIM_ARCHIVE_CONFIG':str(config)}
    helpers=list((ROOT/'historical/runtime').rglob('*.sh'))
    assert len(helpers)==5
    for helper in helpers:
        guard=helper.read_text().splitlines()[1]
        proc=subprocess.run(['sh','-c',guard+'\nprintf BODY_ADMITTED',str(helper)],
                            env=env,text=True,capture_output=True)
        assert proc.returncode!=0,helper
        assert 'BODY_ADMITTED' not in proc.stdout


def test_archived_shell_guards_accept_only_complete_explicit_authorization(tmp_path):
    import os

    config=tmp_path/'bindings.toml'
    config.write_text('[execution]\nallow_side_effects = true\n')
    base={'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'],
          'PYTHONDONTWRITEBYTECODE':'1','BIOSIM_ARCHIVE_ENABLE':'1',
          'BIOSIM_ALLOW_LIVE':'1','BIOSIM_ARCHIVE_CONFIG':str(config)}
    for helper in (ROOT/'historical/runtime').rglob('*.sh'):
        guard=helper.read_text().splitlines()[1]
        for missing in (None,'BIOSIM_ARCHIVE_ENABLE','BIOSIM_ALLOW_LIVE','BIOSIM_ARCHIVE_CONFIG'):
            env=dict(base)
            if missing is not None:
                env.pop(missing)
            proc=subprocess.run(['sh','-c',guard+'\nprintf BODY_ADMITTED',str(helper)],
                                env=env,text=True,capture_output=True)
            assert (proc.returncode==0)==(missing is None)
            assert ('BODY_ADMITTED' in proc.stdout)==(missing is None)


def test_archive_binding_inventory_matches_all_use_sites():
    inventory=json.loads((ROOT/'historical/inventory.json').read_text())
    aliases={'_archive_path','_archive_setting','_archive_port','_archive_credential'}
    actual={}
    for entry in inventory['files']:
        if entry['disposition']!='archival-code' or not entry['path'].endswith('.py'):continue
        tree=ast.parse((ROOT/'historical'/entry['path']).read_text())
        for node in ast.walk(tree):
            if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Name) or node.func.id not in aliases:continue
            assert node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str)
            name=node.args[0].value
            actual.setdefault(name,set()).add((entry['path'],node.lineno))
            assert name in inventory['required_settings']
            if node.func.id=='_archive_port':assert inventory['required_settings'][name]=='port'
            if node.func.id=='_archive_credential':assert inventory['required_settings'][name]=='credential_file'
    recorded={name:{(use['file'],use['line']) for use in uses} for name,uses in inventory['setting_uses'].items()}
    assert actual==recorded
    assert set(actual)==set(inventory['required_settings'])
