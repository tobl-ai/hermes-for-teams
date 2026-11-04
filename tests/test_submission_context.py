"""New-core submission identity survives policy execution and scope restoration."""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip('gateway.turn_scheduling')
display = pytest.importorskip('gateway.session_display')
if not hasattr(display, 'admission_submission'):
    pytest.skip('core predates submission identity', allow_module_level=True)


def test_submission_identity_and_profile_scope_survive_scheduling(tmp_path, monkeypatch):
    async def case():
        from gateway import session_ingress
        from gateway.run import _profile_runtime_scope
        from gateway.session_contract import SessionRef
        from gateway.session_finite import execute_finite_admission
        from hermes_cli.plugins import get_plugin_manager
        from hermes_constants import get_hermes_home

        launch, routed = tmp_path / 'launch', tmp_path / 'profiles' / 'routed'
        launch.mkdir()
        routed.mkdir(parents=True)
        event = SimpleNamespace(message_id='admission')
        seen = []

        async def policy(next_call, **metadata):
            assert get_hermes_home() == routed
            assert display.admission_submission(event) == {'submission_id': 'client-request'}
            assert 'submission_id' not in metadata  # identity is not plugin authority
            seen.append('policy')
            return await next_call()

        with _profile_runtime_scope(launch):
            get_plugin_manager()._discovered = True
        with _profile_runtime_scope(routed):
            manager = get_plugin_manager()
            manager._discovered = True
            monkeypatch.setattr(manager, '_middleware', {'gateway_turn_execution': [policy]})

        row = {'admission_id': 'admission', 'request_id': 'client-request',
               'payload': {'text': '원래 요청', 'finite': False}}

        async def native(authority, ref, passed_row):
            assert passed_row is row
            assert display.admission_submission(event) == {'submission_id': 'client-request'}
            assert display.admission_submission(SimpleNamespace(message_id='other')) == {}
            seen.append('native')
            return 'native-result'

        monkeypatch.setattr(session_ingress, 'execute_admission', native)
        authority = SimpleNamespace(profile_id=str(routed), runner=SimpleNamespace(
            config=SimpleNamespace(multiplex_profiles=True)))
        with _profile_runtime_scope(launch):
            assert await execute_finite_admission(authority, SessionRef(str(routed), 's'), row) == 'native-result'
            assert get_hermes_home() == launch
            assert display.admission_submission(event) == {}
        assert seen == ['policy', 'native']

    asyncio.run(case())
