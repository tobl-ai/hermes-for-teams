from pathlib import Path
import sys

import pytest

from hermes_for_teams.gateway_query import owner_paths, check_contract
from hermes_for_teams.worker import hermes_command


def test_explicit_owner_transport_never_uses_auto_starting_chat(tmp_path):
    control = tmp_path / 'control'
    profile = tmp_path / 'profile'
    control.mkdir()
    profile.mkdir()
    settings = {'allow_cli_workers': True, 'profile': 'test',
                'hermes_executable': '/usr/bin/false',
                'existing_owner_control_home': str(control),
                'existing_owner_profile_home': str(profile)}
    argv = hermes_command(settings, {'payload': 'only echo a test token'})
    assert argv[0] == sys.executable
    assert Path(argv[1]).name == 'gateway_query.py'
    assert '--control-home' in argv and '--profile-home' in argv
    assert argv[argv.index('--prompt') + 1] == 'only echo a test token'
    assert 'chat' not in argv and '--yolo' not in argv


def test_optional_owner_config_is_complete_and_absolute(tmp_path):
    assert owner_paths({}) is None
    with pytest.raises(ValueError):
        owner_paths({'existing_owner_control_home': str(tmp_path)})
    with pytest.raises(ValueError):
        owner_paths({'existing_owner_control_home': '.', 'existing_owner_profile_home': str(tmp_path)})
    assert owner_paths({'existing_owner_control_home': str(tmp_path),
                        'existing_owner_profile_home': str(tmp_path)}) == (tmp_path.resolve(), tmp_path.resolve())


def test_mismatched_profile_and_unsupported_contract_fail_closed(tmp_path):
    good = {'profile_id': str(tmp_path.resolve()),
            'session_create': {'sources': ['oneshot'], 'parameters': ['cwd', 'title', 'request_id']}}
    check_contract(good, tmp_path)
    with pytest.raises(ValueError):
        check_contract(dict(good, profile_id='/other-profile'), tmp_path)
    with pytest.raises(ValueError):
        check_contract(dict(good, session_create={'sources': ['oneshot'], 'parameters': ['title']}), tmp_path)
