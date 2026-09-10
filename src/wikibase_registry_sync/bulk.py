"""Disk-backed initial-load jobs. No source-driven updates or deletions."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

import ijson

from .action_api import canonical, claim_values, snak, statement
from .core import validate
from .local_import import META


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def registry_config(registry):
    config = {k: registry[k] for k in ('target', 'properties', 'meta')}
    if not all(k in config['meta'] for k in META):
        raise ValueError('bootstrap metadata first')
    ids = list(config['properties'].values()) + list(config['meta'].values())
    if len(ids) != len(set(ids)) or not all(re.fullmatch(r'P[1-9][0-9]*', p) for p in ids):
        raise ValueError('invalid or overlapping property mappings')
    return config


def all_snaks(record):
    for claim in record.get('statements', []):
        yield claim
        yield from claim.get('qualifiers', [])
        for reference in claim.get('references', []):
            yield from reference


def desired(record, dataset, registry):
    def mapped(s):
        if s['datatype'] == 'wikibase-item':
            raise ValueError('reviewed local item mappings are not implemented')
        return snak(registry['properties'][s['property']], s['datatype'], s['value'])
    meta = registry['meta']
    claims = [statement(meta['key'], 'external-id', dataset + ':' + record['key'])]
    for source in record.get('statements', []):
        claim = {'type': 'statement', 'rank': 'normal', 'mainsnak': mapped(source)}
        if source.get('qualifiers'):
            claim['qualifiers'] = {}
            for value in source['qualifiers']:
                q = mapped(value)
                claim['qualifiers'].setdefault(q['property'], []).append(q)
        if source.get('references'):
            claim['references'] = []
            for reference in source['references']:
                values = {}
                for value in reference:
                    q = mapped(value)
                    values.setdefault(q['property'], []).append(q)
                claim['references'].append({'snaks': values})
        claims.append(claim)
    if record.get('wikidata_qid'):
        decision = record.get('match_decision', {})
        if decision.get('status') != 'confirmed' or decision.get('qid') != record['wikidata_qid']:
            raise ValueError('QID requires a matching confirmed decision')
        claims += [statement(meta['qid'], 'external-id', record['wikidata_qid']),
                   statement(meta['url'], 'url', 'https://www.wikidata.org/entity/' + record['wikidata_qid'])]
    return {'labels': {lang: {'language': lang, 'value': value} for lang, value in record['labels'].items()},
            'claims': claims}


def differences(entity, data, registry):
    """Require equal source-owned properties; tolerate unrelated human statements.

    A previously confirmed QID is retained when the incoming dataset has no QID.
    Missing QID never means an instruction to unlink.
    """
    issues = []
    for lang, label in data['labels'].items():
        if entity.get('labels', {}).get(lang, {}).get('value') != label['value']:
            issues.append('label:' + lang)
    groups = {}
    for claim in data['claims']:
        groups.setdefault(claim['mainsnak']['property'], []).append(claim)
    for prop, wanted in groups.items():
        actual = entity.get('claims', {}).get(prop, [])
        if canonical(actual) != canonical(wanted):
            issues.append('claims:' + prop)
    # Initial-load must not silently declare a stale source property synchronized.
    for prop in registry['properties'].values():
        if prop not in groups and entity.get('claims', {}).get(prop):
            issues.append('unexpected:' + prop)
    return issues


def prepare(bundle_path, registry, job_path, progress=lambda count: None):
    """Validate the ENTIRE snapshot before publishing an executable job."""
    job_path = Path(job_path)
    config = registry_config(registry)
    with locked(str(job_path) + '.lock'):
        if job_path.exists():
            raise ValueError('job already exists; use run to resume, or a new job path')
        before = digest(bundle_path)
        headers = {}; root_keys = set(); has_entities = False
        with Path(bundle_path).open('rb') as source:
            for prefix, event, value in ijson.parse(source):
                if prefix == '' and event == 'map_key':
                    if value in root_keys:
                        raise ValueError('duplicate top-level field')
                    root_keys.add(value)
                if prefix in ('schema_version', 'dataset', 'validation_status') and event == 'string':
                    headers[prefix] = value
                if prefix == 'entities' and event == 'start_array':
                    has_entities = True
        if not has_entities:
            raise ValueError('entities array required')
        validate(dict(schema_version=headers.get('schema_version'), dataset=headers.get('dataset'), entities=[]))
        if ':' in headers['dataset']:
            raise ValueError('dataset must not contain the registry-key separator colon')
        if headers.get('validation_status') != 'complete':
            raise ValueError('full snapshot must explicitly declare validation_status=complete')
        fd, temp = tempfile.mkstemp(prefix=job_path.name + '.', dir=job_path.parent)
        os.close(fd)
        db = sqlite3.connect(temp)
        try:
            db.executescript('''
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE records (
                    seq INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', entity_id TEXT, revision INTEGER,
                    outcome TEXT, error TEXT);
                CREATE INDEX records_status ON records(status,seq);
                CREATE INDEX records_remaining ON records(seq) WHERE status != 'done';
                CREATE TABLE verification (key TEXT PRIMARY KEY, entity_id TEXT, error TEXT);
                CREATE TABLE remote (key TEXT PRIMARY KEY, entity_id TEXT NOT NULL);
            ''')
            count = 0; types = {}
            with Path(bundle_path).open('rb') as source:
                for record in ijson.items(source, 'entities.item'):
                    validate(dict(schema_version='0.1', dataset=headers['dataset'], entities=[record]))
                    for s in all_snaks(record):
                        pid = s['property']
                        if pid in types and types[pid] != s['datatype']:
                            raise ValueError('inconsistent datatype for ' + pid)
                        types[pid] = s['datatype']
                    payload = desired(record, headers['dataset'], config)
                    count += 1
                    db.execute('INSERT INTO records(seq,key,payload) VALUES(?,?,?)',
                               (count, headers['dataset'] + ':' + record['key'], encoded(payload)))
                    if count % 1000 == 0:
                        db.commit(); progress(count)
            if not count:
                raise ValueError('empty full snapshot refused')
            if digest(bundle_path) != before:
                raise ValueError('source changed during preparation')
            metadata = dict(job_version='1', mode='initial-load', dataset=headers['dataset'],
                            bundle_sha256=before, registry=config, types=types, total=count)
            db.executemany('INSERT INTO meta VALUES(?,?)', [(k, encoded(v)) for k, v in metadata.items()])
            db.commit(); db.close()
            os.replace(temp, job_path)
        finally:
            db.close()
            if os.path.exists(temp):
                os.unlink(temp)
    return status(job_path)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    # No accidental empty DB on a misspelled resume path.
    if not Path(path).is_file():
        raise ValueError('prepared job does not exist')
    db = sqlite3.connect(path, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    return db


def metadata(db):
    data = {row['key']: json.loads(row['value']) for row in db.execute('SELECT * FROM meta')}
    if data['job_version'] != '1' or data['mode'] != 'initial-load':
        raise ValueError('unsupported job version or mode')
    return data


def status(path):
    with connect(path) as db:
        meta = metadata(db)
        counts = dict(db.execute('SELECT status,count(*) FROM records GROUP BY status'))
        outcomes = dict(db.execute('SELECT outcome,count(*) FROM records WHERE outcome IS NOT NULL GROUP BY outcome'))
        return dict(mode=meta['mode'], dataset=meta['dataset'], total=meta['total'], counts=counts,
                    last_verification=meta.get('last_verification'),
                    outcomes=outcomes, complete=counts.get('done', 0) == meta['total'],
                    bundle_sha256=meta['bundle_sha256'], target=meta['registry']['target'])


def validate_target(api, meta):
    registry = meta['registry']
    if api.identity != registry['target']:
        raise ValueError('job target identity mismatch')
    props = {pid: api.entity(pid) for pid in set(registry['properties'].values()) | set(registry['meta'].values())}
    for key, (_, _, datatype) in META.items():
        if props[registry['meta'][key]]['datatype'] != datatype:
            raise ValueError('metadata datatype mismatch: ' + key)
    for wd, local in registry['properties'].items():
        prop = props[local]
        if claim_values(prop, registry['meta']['pid']) != [wd]:
            raise ValueError('Wikidata PID mapping mismatch: ' + wd)
        if wd in meta['types'] and prop['datatype'] != meta['types'][wd]:
            raise ValueError('target datatype mismatch: ' + wd)


def index_target(api, db, meta):
    """One paginated, batched inventory, rather than a scan for every record."""
    db.execute('DELETE FROM remote')
    prefix = meta['dataset'] + ':'
    for entity in api.iter_entities(120):
        keys = claim_values(entity, meta['registry']['meta']['key'])
        for key in keys:
            if isinstance(key, str) and key.startswith(prefix):
                try:
                    db.execute('INSERT INTO remote VALUES(?,?)', (key, entity['id']))
                except sqlite3.IntegrityError as exc:
                    raise ValueError('duplicate target registry key: ' + key) from exc
    db.commit()


def run(api, path, limit=None, progress=lambda result: None, verify_only=False):
    """Single writer. An uncertain create is never automatically re-issued."""
    if limit is not None and limit <= 0:
        raise ValueError('limit must be positive')
    with locked(str(path) + '.lock'), connect(path) as db:
        meta = metadata(db)
        validate_target(api, meta)
        # Same-host jobs for this dataset/target must share the job directory.
        namespace = hashlib.sha256(encoded([api.identity, meta['dataset']]).encode()).hexdigest()
        with locked(Path(path).parent / (namespace + '.writer.lock')):
            index_target(api, db, meta)
            if verify_only:
                return verify(api, db, meta, progress)
            # Inflight means the last process may have committed before disconnecting.
            db.execute("UPDATE records SET status='uncertain' WHERE status='inflight'")
            db.commit()
            processed = 0
            while limit is None or processed < limit:
                row = db.execute("SELECT * FROM records WHERE status!='done' ORDER BY seq LIMIT 1").fetchone()
                if row is None:
                    break
                data = json.loads(row['payload'])
                found = db.execute('SELECT entity_id FROM remote WHERE key=?', (row['key'],)).fetchone()
                if found:
                    entity = api.entity(found['entity_id'])
                    issues = differences(entity, data, meta['registry'])
                    if issues:
                        db.execute("UPDATE records SET status='conflict',entity_id=?,error=? WHERE key=?",
                                   (entity['id'], encoded(issues), row['key']))
                        db.commit(); break
                    outcome = 'reconciled' if row['status'] in ('uncertain', 'inflight') else 'existing'
                elif row['status'] == 'uncertain':
                    # Absence from an inventory does not prove a timed-out write failed.
                    break
                elif row['status'] == 'conflict':
                    break
                else:
                    db.execute("UPDATE records SET status='inflight',entity_id=NULL,error=NULL WHERE key=?", (row['key'],))
                    db.commit()
                    try:
                        created = api.edit(data, new='item')
                        # Persist the returned ID before read-back, for operator diagnosis.
                        db.execute('UPDATE records SET entity_id=? WHERE key=?', (created['id'], row['key']))
                        db.commit()
                        entity = api.entity(created['id'])
                        if differences(entity, data, meta['registry']):
                            raise ValueError('read-back mismatch')
                    except Exception as exc:
                        db.execute("UPDATE records SET status='uncertain',error=? WHERE key=?",
                                   (type(exc).__name__, row['key']))
                        db.commit(); break
                    outcome = 'created'
                    db.execute('INSERT INTO remote VALUES(?,?)', (row['key'], entity['id']))
                db.execute("UPDATE records SET status='done',entity_id=?,revision=?,outcome=?,error=NULL WHERE key=?",
                           (entity['id'], entity['lastrevid'], outcome, row['key']))
                db.commit(); processed += 1
                if processed % 100 == 0:
                    progress({'processed_this_run': processed, 'last_key': row['key']})
    return status(path)


def verify(api, db, meta, progress):
    checked = 0; errors = 0
    db.execute('DELETE FROM verification')
    cursor = db.execute('SELECT * FROM records ORDER BY seq')
    while rows := cursor.fetchmany(50):
        located = {row['key']: db.execute('SELECT entity_id FROM remote WHERE key=?', (row['key'],)).fetchone() for row in rows}
        ids = list({found['entity_id'] for found in located.values() if found})
        entities = api.entities(ids)
        for row in rows:
            found = located[row['key']]
            issues = ['missing'] if not found else differences(entities[found['entity_id']], json.loads(row['payload']), meta['registry'])
            db.execute('INSERT INTO verification VALUES(?,?,?)', (row['key'], found['entity_id'] if found else None, encoded(issues) if issues else None))
            if issues:
                errors += 1
            checked += 1
        if checked % 1000 == 0:
            progress({'verified': checked, 'errors': errors})
    result = {'verified': checked, 'errors': errors, 'passed': errors == 0, 'target': api.identity}
    db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', ('last_verification', encoded(result)))
    db.commit()
    return result
