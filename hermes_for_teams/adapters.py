"""Documented, non-executing bridge to the existing hermes-workflows tool."""


def workflow_request(prompt):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 65536:
        raise ValueError('Prompt must be 1..65536 bytes')
    # Leave model/provider/profile selection to the existing owner policy.
    # This is a separate explicit handoff, NOT an automatically scheduled queue job.
    return {'action': 'run', 'graph': {
        'name': 'teams-long-task', 'concurrency': 1,
        'nodes': [{'id': 'work', 'type': 'agent', 'goal': prompt}]
    }}
