import copy
import unittest
from wikibase_registry_sync.action_api import LocalAPI,APIError,NoRedirect,statement,missing_claims
from wikibase_registry_sync.local_import import Importer
class LocalTests(unittest.TestCase):
    def test_external_target_rejected_before_network(self):
        for endpoint in ('https://example.org/api.php','http://user:pass@localhost/api.php','http://localhost/api.php?x=1'):
            with self.assertRaises(ValueError):LocalAPI(endpoint,'test')
    def test_redirect_refused(self):
        with self.assertRaises(APIError):NoRedirect().redirect_request(None,None,302,'',{},'https://example.org')
    def test_claim_replay_and_reference_distinction(self):
        desired=statement('P1','string','value',[{'snaks':{'P2':[statement('P2','url','https://example.org')['mainsnak']]}}])
        remote=copy.deepcopy(desired);remote['id']='Q1$abc';remote['references'][0]['hash']='abc';remote['references'][0]['snaks-order']=['P2']
        entity={'claims':{'P1':[remote]}}
        self.assertEqual(missing_claims(entity,[desired]),[])
        changed=copy.deepcopy(desired);changed['references'][0]['snaks']['P2'][0]['datavalue']['value']='https://different.org'
        self.assertEqual(len(missing_claims(entity,[changed])),1)
    def test_state_cannot_move_to_other_target(self):
        class Fake:identity={'wikiid':'second'}
        with self.assertRaises(ValueError):Importer(Fake(),'unused',{'target':{'wikiid':'first'}})

class InventoryTests(unittest.TestCase):
    def test_batched_inventory_over_multiple_pages(self):
        from wikibase_registry_sync.action_api import ActionAPI
        class Fake(ActionAPI):
            def __init__(self):
                self.batch_sizes=[]
            def call(self, **params):
                if params['action']=='query':
                    offset=int(params.get('apcontinue',0));end=min(offset+500,1203)
                    result={'query':{'allpages':[{'title':'Item:Q'+str(i+1)} for i in range(offset,end)]}}
                    if end<1203:result['continue']={'apcontinue':str(end),'continue':'-||'}
                    return result
                ids=params['ids'].split('|');self.batch_sizes.append(len(ids))
                return {'entities':{identifier:{'id':identifier} for identifier in ids}}
        api=Fake();entities=list(api.iter_entities(120))
        self.assertEqual(len(entities),1203)
        self.assertEqual(entities[-1]['id'],'Q1203')
        self.assertEqual(max(api.batch_sizes),50)
        self.assertEqual(len(api.batch_sizes),25)
    def test_nonlocal_plain_http_rejected(self):
        from wikibase_registry_sync.action_api import ActionAPI
        with self.assertRaises(ValueError):ActionAPI('http://example.org/api.php','test')
