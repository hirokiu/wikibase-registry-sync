import hashlib
import json
import re

TYPES={"string","external-id","url","monolingualtext","wikibase-item"}

def validate(bundle):
    if bundle.get("schema_version") != "0.1": raise ValueError("unsupported schema version")
    if not isinstance(bundle.get("dataset"),str) or not bundle["dataset"]: raise ValueError("dataset required")
    if not isinstance(bundle.get("entities"),list): raise ValueError("entities required")
    keys=set()
    def snak(s):
        if not re.fullmatch(r"P[1-9][0-9]*",s.get("property","")): raise ValueError("invalid WD property")
        t=s.get("datatype"); v=s.get("value")
        if t not in TYPES: raise ValueError("unsupported datatype: "+str(t))
        if t=="monolingualtext":
            if not isinstance(v,dict) or not all(isinstance(v.get(k),str) and v[k] for k in ("language","text")): raise ValueError("invalid monolingualtext")
        elif not isinstance(v,str) or not v: raise ValueError("nonempty string required")
        if t=="wikibase-item" and not re.fullmatch(r"Q[1-9][0-9]*",v): raise ValueError("invalid item ID")
        if t=="url" and not v.startswith(("https://","http://")): raise ValueError("invalid URL")
    for e in bundle["entities"]:
        key=e.get("key")
        if not isinstance(key,str) or not key or key in keys: raise ValueError("missing/duplicate entity key")
        keys.add(key)
        if not isinstance(e.get("labels"),dict) or not e["labels"] or not all(isinstance(v,str) and v for v in e["labels"].values()): raise ValueError("labels required")
        if e.get("wikidata_qid") and not re.fullmatch(r"Q[1-9][0-9]*",e["wikidata_qid"]): raise ValueError("invalid QID")
        for s in e.get("statements",[]):
            snak(s)
            for q in s.get("qualifiers",[]): snak(q)
            for ref in s.get("references",[]):
                for q in ref: snak(q)
    return bundle

def plan(bundle, registry):
    validate(bundle)
    properties=registry.get("properties",{}); items=registry.get("items",{})
    def mapped(s):
        pid=properties.get(s["property"])
        if not isinstance(pid,str) or not re.fullmatch(r"P[1-9][0-9]*",pid): raise ValueError("missing/invalid target property: "+s["property"])
        value=s["value"]
        if s["datatype"]=="wikibase-item":
            value=items.get(value)
            if not isinstance(value,str) or not re.fullmatch(r"Q[1-9][0-9]*",value): raise ValueError("missing target item mapping")
        return dict(property=pid,datatype=s["datatype"],value=value)
    planned=[]
    for e in bundle["entities"]:
        statements=[]
        for s in e.get("statements",[]):
            out=mapped(s)
            out["qualifiers"]=[mapped(q) for q in s.get("qualifiers",[])]
            out["references"]=[[mapped(q) for q in r] for r in s.get("references",[])]
            statements.append(out)
        if e.get("wikidata_qid"):
            p=registry.get("wikidata_link_property")
            if not isinstance(p,str) or not re.fullmatch(r"P[1-9][0-9]*",p): raise ValueError("configure target URL property for Wikidata link")
            statements.append(dict(property=p,datatype="url",value="https://www.wikidata.org/entity/"+e["wikidata_qid"],qualifiers=[],references=[]))
        planned.append(dict(key=e["key"],labels=e["labels"],statements=statements))
    canonical=json.dumps(bundle,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return dict(plan_version="0.1",dataset=bundle["dataset"],bundle_sha256=hashlib.sha256(canonical).hexdigest(),
                mode="offline-plan",entities=planned,
                warning="Not a live diff: target entities, datatypes and existing statements have not been fetched. No writes performed.")
