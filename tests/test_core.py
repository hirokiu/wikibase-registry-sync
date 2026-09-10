import copy
import unittest
from wikibase_registry_sync.core import validate, plan
class CoreTest(unittest.TestCase):
    def setUp(self):
        self.b={"schema_version":"0.1","dataset":"demo","entities":[{"key":"a","labels":{"ja":"例"},"statements":[{"property":"P13179","datatype":"external-id","value":"1310270751","references":[[{"property":"P854","datatype":"url","value":"https://example.org/"}]]}]}]}
    def test_maps_references(self):
        p=plan(self.b,{"properties":{"P13179":"P12","P854":"P8"}})
        self.assertEqual(p["entities"][0]["statements"][0]["references"][0][0]["property"],"P8")
        self.assertEqual(self.b["entities"][0]["statements"][0]["property"],"P13179")
    def test_missing_mapping(self):
        with self.assertRaises(ValueError): plan(self.b,{})
    def test_duplicate(self):
        self.b["entities"].append(copy.deepcopy(self.b["entities"][0]))
        with self.assertRaises(ValueError): validate(self.b)
    def test_wikidata_link(self):
        self.b["entities"][0]["wikidata_qid"]="Q7589810"
        p=plan(self.b,{"properties":{"P13179":"P12","P854":"P8"},"wikidata_link_property":"P20"})
        self.assertEqual(p["entities"][0]["statements"][-1]["value"],"https://www.wikidata.org/entity/Q7589810")
