"""Generic, append-only, small-batch importer; not a production synchronization engine."""
from .action_api import statement, snak, claim_values, missing_claims, save_state
from .core import validate

META = {
 'pid':('Wikidata property ID','WikidataプロパティID','external-id'),
 'qid':('Wikidata item ID','Wikidata項目ID','external-id'),
 'url':('Wikidata entity URL','WikidataエンティティURL','url'),
 'key':('Registry record key','レジストリレコードキー','external-id'),
}

class Importer:
    def __init__(self, api, state_path, state):
        self.api=api;self.path=state_path;self.state=state
        if state.get('target') not in (None,api.identity):raise ValueError('registry target differs')
        self.state['target']=api.identity
        self.state.setdefault('properties',{});self.state.setdefault('meta',{});self.state.setdefault('entities',{})
        self.mutations=0

    def checkpoint(self):save_state(self.path,self.state)

    def create(self,data,new='item'):
        result=self.api.edit(data,new=new);self.mutations+=1;return result

    def add(self,entity,claims):
        missing=missing_claims(entity,claims)
        if missing:
            entity=self.api.edit({'claims':missing},identifier=entity['id'],revision=entity['lastrevid']);self.mutations+=1
        return entity

    def bootstrap(self, definitions):
        existing=self.api.all_entities(122)
        for key,(en,ja,datatype) in META.items():
            known=self.state['meta'].get(key)
            matches=[e for e in existing if e.get('labels',{}).get('en',{}).get('value')==en]
            if known:matches=[self.api.entity(known)]
            if len(matches)>1:raise ValueError('ambiguous metadata property: '+key)
            if matches:
                entity=matches[0]
                if entity.get('datatype')!=datatype:raise ValueError('metadata datatype mismatch')
            else:
                entity=self.create({'datatype':datatype,'labels':{'en':{'language':'en','value':en},'ja':{'language':'ja','value':ja}},
                  'descriptions':{'en':{'language':'en','value':'Registry integration metadata; external Wikidata identifiers are not local entity IDs.'}}},'property')
                existing.append(entity)
            self.state['meta'][key]=entity['id'];self.checkpoint()
        for pid,definition in definitions.items():
            matches=[e for e in existing if pid in claim_values(e,self.state['meta']['pid'])]
            if len(matches)>1:raise ValueError('duplicate Wikidata PID mapping: '+pid)
            known=self.state['properties'].get(pid)
            if known:
                current=self.api.entity(known)
                if pid not in claim_values(current,self.state['meta']['pid']):raise ValueError('lost PID statement')
                matches=[current]
            claims=[statement(self.state['meta']['pid'],'external-id',pid),
                    statement(self.state['meta']['url'],'url','https://www.wikidata.org/entity/'+pid)]
            if matches:
                entity=matches[0]
                if entity.get('datatype')!=definition['datatype']:raise ValueError('property datatype mismatch: '+pid)
                entity=self.add(entity,claims)
            else:
                labels={lang:definition['labels'][lang] for lang in ('ja','en') if lang in definition['labels']}
                descriptions={lang:definition['descriptions'][lang] for lang in ('ja','en') if lang in definition.get('descriptions',{})}
                entity=self.create({'datatype':definition['datatype'],'labels':labels,'descriptions':descriptions,'claims':claims},'property')
                existing.append(entity)
            self.state['properties'][pid]=entity['id'];self.checkpoint()
        return self.state

    def apply(self,bundle):
        validate(bundle)
        if bundle.get('validation_status') not in (None,'complete'):raise ValueError('incomplete source bundle')
        if len(bundle['entities'])>10:raise ValueError('experimental local batch limit: 10 entities')
        for record in bundle['entities']:
            if record.get('wikidata_qid'):
                decision=record.get('match_decision',{})
                if decision.get('status')!='confirmed' or decision.get('qid')!=record['wikidata_qid']:
                    raise ValueError('QID requires a matching confirmed decision')
            for s in record.get('statements',[]):
                if s['property'] not in self.state['properties']:raise ValueError('unknown property mapping')
                if s['datatype']=='wikibase-item':raise ValueError('item-valued imports require reviewed local item mappings; unsupported in this writer')
        inventory=self.api.all_entities(120);results=[]
        def mapped(s):
            p=self.state['properties'][s['property']]
            if self.api.entity(p)['datatype']!=s['datatype']:raise ValueError('target datatype mismatch')
            return snak(p,s['datatype'],s['value'])
        for record in bundle['entities']:
            key=bundle['dataset']+':'+record['key']
            matches=[e for e in inventory if key in claim_values(e,self.state['meta']['key'])]
            if len(matches)>1:raise ValueError('duplicate record key')
            if not matches:
                # Reconcile existing records by an explicitly configured identity property.
                identity=self.state.get('identity_property')
                identity_claims=[s for s in record['statements'] if s['property']==identity]
                if identity_claims:
                    p=self.state['properties'][identity];v=identity_claims[0]['value']
                    matches=[e for e in inventory if v in claim_values(e,p)]
                    if len(matches)>1:raise ValueError('duplicate source identifier')
            claims=[statement(self.state['meta']['key'],'external-id',key)]
            for s in record['statements']:
                claim={'type':'statement','rank':'normal','mainsnak':mapped(s)}
                if s.get('qualifiers'):
                    claim['qualifiers']={}
                    for q in s['qualifiers']:
                        qs=mapped(q);claim['qualifiers'].setdefault(qs['property'],[]).append(qs)
                if s.get('references'):
                    claim['references']=[]
                    for ref in s['references']:
                        snaks={}
                        for q in ref:
                            rs=mapped(q);snaks.setdefault(rs['property'],[]).append(rs)
                        claim['references'].append({'snaks':snaks})
                claims.append(claim)
            if record.get('wikidata_qid'):
                qid=record['wikidata_qid']
                claims.extend([statement(self.state['meta']['qid'],'external-id',qid),statement(self.state['meta']['url'],'url','https://www.wikidata.org/entity/'+qid)])
            if matches:
                entity=matches[0]
                old=claim_values(entity,self.state['meta']['qid'])
                if old and record.get('wikidata_qid') and old!=[record['wikidata_qid']]:raise ValueError('conflicting QID')
                entity=self.add(entity,claims)
            else:
                entity=self.create({'labels':{k:{'language':k,'value':v} for k,v in record['labels'].items()},'claims':claims})
                inventory.append(entity)
            self.state['entities'][key]=entity['id'];self.checkpoint()
            results.append({'key':key,'id':entity['id'],'revision':entity['lastrevid'],'wikidata_qid':record.get('wikidata_qid')})
        return {'target':self.api.identity,'entities':results,'mutations':self.mutations}
