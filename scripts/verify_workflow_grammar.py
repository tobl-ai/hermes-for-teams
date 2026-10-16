"""Optional pinned third-party graph validator probe, NOT workflow execution."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hermes_for_teams.adapters import workflow_request

REVISION = 'b1bf8cc99d5113cfaf8251122ce4f4492838bad8'
URL = f'https://raw.githubusercontent.com/jacobhausler/hermes-workflows/{REVISION}/wfcommon.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='hermes-teams-grammar-', dir=args.scratch) as temp:
        module_path = Path(temp) / 'wfcommon.py'
        with urllib.request.urlopen(URL, timeout=30) as response:
            module_path.write_bytes(response.read())
        spec = importlib.util.spec_from_file_location('workflow_validator_fixture', module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        graph = workflow_request('Return a short research summary')['graph']
        errors = module.validate_graph_full(graph)
        assert errors == [], errors
        print(json.dumps({'probe': 'pinned workflow graph grammar', 'revision': REVISION,
                          'errors': errors, 'workflow_executed': False, 'provider_calls': 0}))


if __name__ == '__main__':
    main()
