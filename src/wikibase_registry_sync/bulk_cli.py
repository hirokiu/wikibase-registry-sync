"""Prepare, run/resume, verify and report full initial-load jobs."""
import argparse
import csv
import json
import os
from pathlib import Path
import sys

from .action_api import ActionAPI
from .bulk import (connect, encoded, locked, metadata, prepare, run, status)
from .local_import import Importer


def progress(value):
    print(encoded(value), file=sys.stderr, flush=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('bootstrap', help='create/reuse explicitly supplied Wikidata property definitions')
    c.add_argument('definitions', type=Path)
    c.add_argument('--registry', type=Path, required=True)
    c.add_argument('--api', required=True)
    c.add_argument('--wikiid', required=True)
    c.add_argument('--interval', type=float, default=0.25)
    c = sub.add_parser('prepare', help='offline validation and disk-backed queue creation; no target writes')
    c.add_argument('bundle', type=Path)
    c.add_argument('--registry', type=Path, required=True)
    c.add_argument('--job', type=Path, required=True)
    c.add_argument('--mode', choices=['initial-load'], default='initial-load')
    for command in ('run', 'verify', 'status', 'export'):
        c = sub.add_parser(command)
        c.add_argument('--job', type=Path, required=True)
        if command in ('run', 'verify'):
            c.add_argument('--interval', type=float, default=0.25, help='minimum seconds between API requests')
        if command == 'run':
            c.add_argument('--max-records', type=int, help='pause after this many records; omission processes all')
        if command == 'export':
            c.add_argument('--output', type=Path, required=True)
    c = sub.add_parser('retry-uncertain', help='operator-only: release one uncertain record after proving no write is pending/committed')
    c.add_argument('--job', type=Path, required=True)
    c.add_argument('--key', required=True)
    c.add_argument('--confirmed-not-created', action='store_true', required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.bundle, json.loads(args.registry.read_text()), args.job, progress)
    elif args.command == 'status':
        result = status(args.job)
    elif args.command == 'bootstrap':
        definitions = json.loads(args.definitions.read_text())
        # Validate every definition before the first property write.
        import re
        for pid, definition in definitions.items():
            if (not re.fullmatch(r'P[1-9][0-9]*', pid) or definition.get('id') != pid
                    or definition.get('type') != 'property' or not definition.get('datatype')
                    or not any(lang in definition.get('labels', {}) for lang in ('ja', 'en'))):
                raise ValueError('invalid Wikidata definition: ' + pid)
        with locked(str(args.registry) + '.lock'):
            api = ActionAPI(args.api, args.wikiid, interval=args.interval)
            api.login(os.environ['WIKIBASE_USER'], os.environ['WIKIBASE_PASSWORD'])
            state = json.loads(args.registry.read_text()) if args.registry.exists() else {}
            importer = Importer(api, args.registry, state)
            importer.bootstrap(definitions)
            result = {'properties': importer.state['properties'], 'meta': importer.state['meta'], 'mutations': importer.mutations}
    elif args.command == 'export':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.resolve() == args.job.resolve():
            raise ValueError('report cannot overwrite the job')
        with connect(args.job) as db, args.output.open('w', encoding='utf-8', newline='') as out:
            writer = csv.writer(out)
            writer.writerow(['key', 'status', 'entity_id', 'revision', 'outcome', 'error', 'verification_error'])
            writer.writerows(db.execute('SELECT r.key,r.status,r.entity_id,r.revision,r.outcome,r.error,v.error FROM records r LEFT JOIN verification v ON r.key=v.key ORDER BY r.seq'))
        result = {'report': str(args.output)}
    elif args.command == 'retry-uncertain':
        with locked(str(args.job) + '.lock'), connect(args.job) as db:
            changed = db.execute("UPDATE records SET status='pending',error='operator confirmed no creation' WHERE key=? AND status='uncertain'", (args.key,)).rowcount
            if changed != 1:
                raise ValueError('exactly one uncertain record must be selected')
        result = status(args.job)
    else:
        with connect(args.job) as db:
            target = metadata(db)['registry']['target']
        api = ActionAPI(target['endpoint'], target['wikiid'], interval=args.interval)
        if args.command == 'run':
            api.login(os.environ['WIKIBASE_USER'], os.environ['WIKIBASE_PASSWORD'])
        result = run(api, args.job, getattr(args, 'max_records', None), progress, verify_only=args.command == 'verify')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'run' and any(result['counts'].get(s, 0) for s in ('conflict', 'uncertain', 'inflight')):
        return 2
    if args.command == 'verify' and not result['passed']:
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
