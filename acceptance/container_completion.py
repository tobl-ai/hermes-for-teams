"""Real Docker daemon gate; explicitly required in CI, never replaced by shell I/O."""
import json
import os
import shlex
import subprocess
import threading
import time
import uuid

import pytest
pytest.importorskip('gateway.task_resources')
from backend_completion import private_backend


@pytest.fixture
def container(tmp_path,monkeypatch):
    if os.environ.get('HERMES_TEAMS_DOCKER_ACCEPTANCE')!='1':
        pytest.skip('Real Docker gate runs in explicitly enabled daemon-capable CI')
    probe=subprocess.run(['docker','info'],capture_output=True,text=True,timeout=20)
    assert probe.returncode==0,'Required Docker daemon is unavailable'
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    from tools.environments.docker import DockerEnvironment
    (tmp_path/'startup').write_text('trap ":" EXIT\nif [ -z "$STARTUP_GATE" ]; then\nexport STARTUP_GATE=1\n'
        '(sleep .3; printf late > /workspace/startup-late) >/dev/null 2>&1 &\nfi\n')
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import reserved_terminal
    guard=ResourceGuard(tmp_path/'resources.db')
    env=reserved_terminal(guard,{},lambda _:DockerEnvironment(image=os.environ.get('HERMES_TEAMS_DOCKER_IMAGE','python:3.12-slim'),
        cwd='/workspace',volumes=[str(tmp_path)+':/workspace'],task_id='teams-gate-'+uuid.uuid4().hex,
        persistent_filesystem=False,persist_across_processes=False,auto_mount_cwd=False,run_as_host_user=True,
        env={'BASH_ENV':'/workspace/startup','HOME':'/workspace'},network=False))
    assert guard.held_count()==0 and (tmp_path/'startup-late').exists()
    try:
        yield env
    finally:
        from tools.code_kernel_remote import shutdown_all_remote_kernels
        shutdown_all_remote_kernels()
        env.cleanup(force_remove=True)


def test_real_docker_shell_startup_and_background_physical_completion(container,tmp_path):
    from gateway.task_resources import ResourceGuard
    from tools.process_resource_contract import reserved_terminal
    from tools.process_registry import process_registry
    guard=ResourceGuard(tmp_path/'resources.db')
    result=reserved_terminal(guard,{},lambda _:container.execute('printf root'))
    assert result['returncode']==0 and (tmp_path/'startup-late').read_text()=='late',result
    assert guard.held_count()==0
    session=reserved_terminal(guard,{},lambda _:process_registry.spawn_via_env(
        container,'sleep .3; printf background > /workspace/bg',cwd='/workspace',task_id='docker-background'))
    deadline=time.monotonic()+15
    try:
        while guard.held_count():
            assert time.monotonic()<deadline
            threading.Event().wait(.05)
        assert (tmp_path/'bg').read_text()=='background'
        assert session._native_remote_receipt.done
    finally:
        process_registry.kill_process(session.id)


def test_real_docker_persistent_kernel_keeps_state_and_owns_native_rpc(container,tmp_path,monkeypatch):
    model,_=private_backend(tmp_path,monkeypatch)
    from tools import terminal_tool
    import tools.code_execution_tool as code_tool
    monkeypatch.setattr(code_tool,'_get_or_create_env',lambda owner:(container,'docker'))
    original=terminal_tool._get_env_config
    monkeypatch.setattr(terminal_tool,'_get_env_config',lambda:{**original(),'env_type':'docker','cwd':'/workspace'})
    def call(code):
        return json.loads(model.handle_function_call('execute_code',{'code':code},
            task_id='docker-kernel',session_id='docker-kernel',enabled_tools=['write_file','patch','read_file'],
            skip_tool_execution_middleware=True))
    path=tmp_path/'native-rpc'
    first=call('state={"value":41};print(state)')
    assert not first.get('error'),first
    second=call(f'from hermes_tools import write_file\nstate["value"]+=1\nprint(state)\nprint(write_file({str(path)!r},"native"))')
    assert not second.get('error') and not second.get('tool_errors'),second
    assert '42' in second['output'] and second['kernel']['reused'],second
    assert path.read_text()=='native'
    from gateway.task_resources import ResourceGuard
    assert ResourceGuard(tmp_path/'resources.db').held_count()==0
