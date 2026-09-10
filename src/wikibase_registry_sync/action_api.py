"""Standard Action API transport; explicit target identity and paced requests."""
import http.cookiejar
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

class APIError(RuntimeError):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise APIError('redirect refused')

class ActionAPI:
    def __init__(self, endpoint, expected_wikiid, *, interval=0.25, loopback_only=False):
        url=urllib.parse.urlsplit(endpoint)
        local = url.hostname in ('127.0.0.1', 'localhost', '::1')
        if (url.scheme not in ('http', 'https') or url.query or url.fragment
                or not url.hostname or not url.path.endswith('/api.php')
                or url.username or url.password or (not local and url.scheme != 'https')
                or (loopback_only and not local)):
            raise ValueError('explicit HTTPS API or loopback HTTP API required')
        if interval < 0:
            raise ValueError('interval must be nonnegative')
        self.interval = interval
        self.last_request = 0.0
        self.endpoint=endpoint
        self.opener=urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf=None
        site=self.call(action='query',meta='siteinfo')['query']['general']
        if site['wikiid']!=expected_wikiid or site['server'].rstrip('/') != urllib.parse.urlunsplit((url.scheme, url.netloc, '', '', '')):
            raise ValueError('target identity mismatch')
        self.identity={'endpoint':endpoint,'wikiid':site['wikiid'],'concept_uri':site.get('wikibase-conceptbaseuri')}

    def call(self, post=False, **params):
        delay = self.interval - (time.monotonic() - self.last_request)
        if delay > 0: time.sleep(delay)
        self.last_request = time.monotonic()
        params.update(format='json',formatversion='2')
        body=urllib.parse.urlencode(params).encode()
        req=urllib.request.Request(self.endpoint if post else self.endpoint+'?'+body.decode(),
                                   data=body if post else None,headers={'User-Agent':'wikibase-registry-sync/0.2'})
        with self.opener.open(req,timeout=45) as response:
            if urllib.parse.urlsplit(response.url).netloc!=urllib.parse.urlsplit(self.endpoint).netloc:
                raise APIError('unexpected target redirect')
            result=json.load(response)
        if 'error' in result:raise APIError('Action API error: '+result['error'].get('code','unknown'))
        return result

    def login(self, user, password):
        token=self.call(action='query',meta='tokens',type='login')['query']['tokens']['logintoken']
        result=self.call(True,action='login',lgname=user,lgpassword=password,lgtoken=token)
        if result['login']['result']!='Success':raise APIError('login failed')
        self.csrf=self.call(action='query',meta='tokens')['query']['tokens']['csrftoken']

    def entity(self, identifier):
        result=self.call(action='wbgetentities',ids=identifier)['entities'][identifier]
        if 'missing' in result:raise APIError('entity missing: '+identifier)
        return result

    def iter_entities(self, namespace):
        continuation = {}
        while True:
            page = self.call(action='query', list='allpages', apnamespace=namespace,
                             aplimit=500, **continuation)
            ids = [entry['title'].split(':')[-1] for entry in page['query']['allpages']]
            for offset in range(0, len(ids), 50):
                yield from self.entities(ids[offset:offset + 50]).values()
            if 'continue' not in page:
                break
            continuation = page['continue']

    def entities(self, identifiers):
        if not identifiers:
            return {}
        result = self.call(action='wbgetentities', ids='|'.join(identifiers))['entities']
        if set(result) != set(identifiers) or any('missing' in entity for entity in result.values()):
            raise APIError('inventory changed: an entity is missing')
        return result

    def all_entities(self, namespace):
        return list(self.iter_entities(namespace))

    def edit(self, data, identifier=None, revision=None, new=None):
        if not self.csrf:raise APIError('login required')
        params=dict(action='wbeditentity',token=self.csrf,data=json.dumps(data,ensure_ascii=False),
                    summary='Registry import: sourced metadata',maxlag=5)
        if identifier:
            if revision is None:raise ValueError('base revision required')
            params.update(id=identifier,baserevid=revision)
        else:params['new']=new or 'item'
        # Never retry an uncertain write; next execution inventories the target first.
        return self.call(True,**params)['entity']

class LocalAPI(ActionAPI):
    def __init__(self, endpoint, expected_wikiid):
        super().__init__(endpoint, expected_wikiid, interval=0, loopback_only=True)

    def all_entities(self, namespace):
        result = []
        for entity in self.iter_entities(namespace):
            result.append(entity)
            if len(result) > 2000:
                raise APIError('local test inventory limit reached')
        return result

def save_state(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(data,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def snak(prop, datatype, value):
    if datatype=='wikibase-item':
        data={'entity-type':'item','numeric-id':int(value[1:]),'id':value};value_type='wikibase-entityid'
    else:data=value;value_type='monolingualtext' if datatype=='monolingualtext' else 'string'
    return {'snaktype':'value','property':prop,'datatype':datatype,'datavalue':{'value':data,'type':value_type}}

def statement(prop,datatype,value,references=None):
    result={'type':'statement','rank':'normal','mainsnak':snak(prop,datatype,value)}
    if references:result['references']=references
    return result

def claim_values(entity, prop):
    return [c.get('mainsnak',{}).get('datavalue',{}).get('value') for c in entity.get('claims',{}).get(prop,[])
            if c.get('rank')!='deprecated']

def canonical(value):
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items() if k not in ('id','hash','snaks-order','qualifiers-order')}
    if isinstance(value,list):return sorted([canonical(v) for v in value],key=lambda v:json.dumps(v,sort_keys=True))
    return value

def missing_claims(entity, desired):
    existing=[canonical(c) for group in entity.get('claims',{}).values() for c in group]
    return [c for c in desired if canonical(c) not in existing]
