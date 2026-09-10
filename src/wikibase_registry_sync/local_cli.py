"""Local smoke-test writer. Credentials come from environment, never state files."""
import argparse
import fcntl
import json
import os
from pathlib import Path
from .action_api import LocalAPI
from .local_import import Importer
from .core import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('definitions', type=Path)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--api', required=True)
    parser.add_argument('--wikiid', required=True)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text())
    definitions = json.loads(args.definitions.read_text())
    validate(bundle)
    if not 0 < len(bundle['entities']) <= 10:
        raise ValueError('local test requires 1–10 records')
    if bundle.get('validation_status') not in (None, 'complete'):
        raise ValueError('incomplete bundle')
    for record in bundle['entities']:
        if record.get('wikidata_qid'):
            decision = record.get('match_decision', {})
            if decision.get('status') != 'confirmed' or decision.get('qid') != record['wikidata_qid']:
                raise ValueError('unconfirmed QID')
        for claim in record['statements']:
            snaks = [claim] + claim.get('qualifiers', [])
            snaks += [s for ref in claim.get('references', []) for s in ref]
            for s in snaks:
                if s['datatype'] == 'wikibase-item' or definitions.get(s['property'], {}).get('datatype') != s['datatype']:
                    raise ValueError('unsupported or inconsistent property definition')
    args.state.parent.mkdir(parents=True, exist_ok=True)
    with args.state.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        api = LocalAPI(args.api, args.wikiid)
        api.login(os.environ['WIKIBASE_USER'], os.environ['WIKIBASE_PASSWORD'])
        state = json.loads(args.state.read_text()) if args.state.exists() else {}
        importer = Importer(api, args.state, state)
        importer.bootstrap(definitions)
        print(json.dumps(importer.apply(bundle), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
