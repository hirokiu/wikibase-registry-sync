import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from wikibase_registry_sync.action_api import statement
from wikibase_registry_sync.bulk import (prepare, run, status, connect, metadata,
                                         desired, differences)
from wikibase_registry_sync.bulk_cli import main

TARGET = {'endpoint': 'http://127.0.0.1:8180/api.php', 'wikiid': 'test', 'concept_uri': 'http://127.0.0.1:8180/entity/'}
REGISTRY = {'target': TARGET, 'properties': {'P13179': 'P5', 'P854': 'P6'},
            'meta': {'pid': 'P1', 'qid': 'P2', 'url': 'P3', 'key': 'P4'}}


def record(i):
    return {'key': str(i), 'labels': {'ja': '施設' + str(i)}, 'statements': [
        {'property': 'P13179', 'datatype': 'external-id', 'value': str(i),
         'references': [[{'property': 'P854', 'datatype': 'url', 'value': 'https://example.org/source'}]]}]}


def remote(identifier, data):
    entity = copy.deepcopy(data)
    claims = {}
    for index, claim in enumerate(entity['claims']):
        claim['id'] = identifier + '$' + str(index)
        claims.setdefault(claim['mainsnak']['property'], []).append(claim)
    entity.update(id=identifier, lastrevid=1, claims=claims)
    return entity


class FakeAPI:
    identity = TARGET

    def __init__(self):
        self.data = {}; self.writes = 0; self.scans = 0; self.fail_after_commit = False; self.fail_before_commit = False
        for key, pid in REGISTRY['meta'].items():
            self.data[pid] = {'id': pid, 'datatype': 'url' if key == 'url' else 'external-id'}
        for wd, pid in REGISTRY['properties'].items():
            self.data[pid] = remote(pid, {'claims': [statement('P1', 'external-id', wd)]})
            self.data[pid]['datatype'] = 'url' if wd == 'P854' else 'external-id'

    def entity(self, identifier):
        return copy.deepcopy(self.data[identifier])

    def entities(self, ids):
        assert len(ids) <= 50
        return {identifier: self.entity(identifier) for identifier in ids}

    def iter_entities(self, namespace):
        self.scans += 1
        yield from [copy.deepcopy(v) for k, v in self.data.items() if k.startswith('Q')]

    def edit(self, data, new):
        assert new == 'item'
        if self.fail_before_commit:
            raise TimeoutError('test')
        self.writes += 1
        identifier = 'Q' + str(self.writes)
        entity = remote(identifier, data)
        self.data[identifier] = entity
        if self.fail_after_commit:
            raise TimeoutError('test')
        return copy.deepcopy(entity)


class BulkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'bundle.json'
        self.job = self.root / 'job.sqlite'
        self.api = FakeAPI()

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, count=3, **extra):
        b = {'schema_version': '0.1', 'dataset': 'example', 'validation_status': 'complete',
             'entities': [record(i) for i in range(count)]}
        b.update(extra)
        self.source.write_text(json.dumps(b))
        return b

    def ready(self, count=3, **extra):
        self.bundle(count, **extra)
        return prepare(self.source, REGISTRY, self.job)

    def test_full_load_resume_and_readonly_verify_over_1000_records(self):
        self.ready(1001)
        first = run(self.api, self.job, limit=51)
        self.assertEqual(first['counts']['done'], 51)
        self.assertFalse(first['complete'])
        result = run(self.api, self.job)
        self.assertTrue(result['complete'])
        self.assertEqual(self.api.writes, 1001)
        self.assertTrue(run(self.api, self.job)['complete'])
        self.assertEqual(self.api.writes, 1001)
        self.assertTrue(run(self.api, self.job, verify_only=True)['passed'])
        self.assertEqual(self.api.scans, 4)

    def test_lost_response_reconciles_without_duplicate(self):
        self.ready(1)
        self.api.fail_after_commit = True
        self.assertEqual(run(self.api, self.job)['counts'], {'uncertain': 1})
        self.api.fail_after_commit = False
        result = run(self.api, self.job)
        self.assertEqual(result['outcomes'], {'reconciled': 1})
        self.assertEqual(self.api.writes, 1)

    def test_uncertain_absence_never_automatically_retries(self):
        self.ready(1)
        self.api.fail_before_commit = True
        run(self.api, self.job)
        self.api.fail_before_commit = False
        self.assertEqual(run(self.api, self.job)['counts'], {'uncertain': 1})
        self.assertEqual(self.api.writes, 0)

    def test_crash_before_result_saved_reconciles(self):
        self.ready(1)
        self.api.edit(desired(record(0), 'example', REGISTRY), new='item')
        with connect(self.job) as db:
            db.execute("UPDATE records SET status='inflight'")
        self.assertTrue(run(self.api, self.job)['complete'])
        self.assertEqual(self.api.writes, 1)

    def test_duplicate_source_fails_before_executable_job(self):
        self.bundle(entities=[record(1), record(1)])
        with self.assertRaises(Exception): prepare(self.source, REGISTRY, self.job)
        self.assertFalse(self.job.exists())
        self.assertEqual(self.api.writes, 0)

    def test_incomplete_and_empty_snapshots_refused(self):
        for kwargs in ({'validation_status': 'partial'}, {'entities': []}):
            self.bundle(**kwargs)
            with self.assertRaises(ValueError): prepare(self.source, REGISTRY, self.job)
            self.assertFalse(self.job.exists())

    def test_invalid_last_record_and_unknown_reference_refused(self):
        rows = [record(1), record(2)]
        rows[-1]['statements'][0]['references'][0][0]['property'] = 'P9999'
        self.bundle(entities=rows)
        with self.assertRaises(KeyError): prepare(self.source, REGISTRY, self.job)
        self.assertFalse(self.job.exists())

    def test_unconfirmed_qid_refused(self):
        r = record(1); r['wikidata_qid'] = 'Q10'
        self.bundle(entities=[r])
        with self.assertRaises(ValueError): prepare(self.source, REGISTRY, self.job)
        self.assertFalse(self.job.exists())

    def test_mismatched_target_fails_before_item_write(self):
        self.ready()
        self.api.identity = dict(TARGET, wikiid='other')
        with self.assertRaises(ValueError): run(self.api, self.job)
        self.assertEqual(self.api.writes, 0)

    def test_changed_property_mapping_fails_before_item_write(self):
        self.ready()
        self.api.data['P5']['claims']['P1'][0]['mainsnak']['datavalue']['value'] = 'P9999'
        with self.assertRaises(ValueError): run(self.api, self.job)
        self.assertEqual(self.api.writes, 0)

    def test_duplicate_target_keys_fail_before_new_write(self):
        self.ready()
        data = desired(record(0), 'example', REGISTRY)
        self.api.data.update(Q50=remote('Q50', data), Q51=remote('Q51', data))
        with self.assertRaises(ValueError): run(self.api, self.job)
        self.assertEqual(self.api.writes, 0)

    def test_existing_conflict_is_not_overwritten(self):
        self.ready(1)
        data = desired(record(0), 'example', REGISTRY)
        data['labels']['ja']['value'] = '人手による変更'
        self.api.data['Q50'] = remote('Q50', data)
        result = run(self.api, self.job)
        self.assertEqual(result['counts'], {'conflict': 1})
        self.assertEqual(self.api.writes, 0)

    def test_existing_same_and_human_claims_untouched(self):
        self.ready(1)
        data = desired(record(0), 'example', REGISTRY)
        data['claims'].append(statement('P100', 'string', '人手で追加'))
        self.api.data['Q50'] = remote('Q50', data)
        self.assertEqual(run(self.api, self.job)['outcomes'], {'existing': 1})
        self.assertEqual(self.api.writes, 0)
        self.assertIn('P100', self.api.data['Q50']['claims'])

    def test_existing_qid_preserved_when_input_has_none(self):
        self.ready(1)
        data = desired(record(0), 'example', REGISTRY)
        data['claims'].append(statement('P2', 'external-id', 'Q100'))
        data['claims'].append(statement('P3', 'url', 'https://www.wikidata.org/entity/Q100'))
        self.api.data['Q50'] = remote('Q50', data)
        self.assertTrue(run(self.api, self.job)['complete'])
        self.assertEqual(self.api.writes, 0)

    def test_verification_detects_drift(self):
        self.ready(1); run(self.api, self.job)
        self.api.data['Q1']['labels']['ja']['value'] = 'changed'
        self.assertFalse(run(self.api, self.job, verify_only=True)['passed'])

    def test_job_cannot_be_overwritten(self):
        self.ready()
        with self.assertRaises(ValueError): prepare(self.source, REGISTRY, self.job)
        self.assertEqual(status(self.job)['total'], 3)

    def test_future_modes_not_silently_accepted(self):
        for mode in ('replace', 'upsert'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(['prepare', str(self.source), '--registry', 'unused', '--job', str(self.job), '--mode', mode])
