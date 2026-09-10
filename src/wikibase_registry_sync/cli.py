import argparse
import json
from .core import validate, plan

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="command",required=True)
    c=sub.add_parser("validate"); c.add_argument("bundle")
    c=sub.add_parser("plan"); c.add_argument("bundle"); c.add_argument("registry")
    a=p.parse_args()
    with open(a.bundle) as f: bundle=json.load(f)
    if a.command=="validate":
        validate(bundle); result={"valid":True,"entities":len(bundle["entities"])}
    else:
        with open(a.registry) as f: registry=json.load(f)
        result=plan(bundle,registry)
    print(json.dumps(result,ensure_ascii=False,indent=2))
