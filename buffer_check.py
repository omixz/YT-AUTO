#!/usr/bin/env python3
"""Manual diagnostic: shows which channels your Buffer key can see (so you can copy the TikTok channel id into the
BUFFER_TIKTOK_CHANNEL_ID secret) and what TikTok-specific fields Buffer's createPost accepts. Writes buffer_report.md."""
import json
import os

import requests

API = "https://api.buffer.com"
KEY = os.environ.get("BUFFER_API_KEY", "")


def gql(query, variables=None):
    r = requests.post(API, headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
                      json={"query": query, "variables": variables or {}}, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:500]}


def type_info(name):
    code, d = gql('{ __type(name: "%s") { kind enumValues { name } inputFields { name type { name kind ofType { name kind } } } } }' % name)
    return (d.get("data") or {}).get("__type")


def show(out, title, obj):
    out += [f"### {title}", "```json", json.dumps(obj, indent=1)[:2200], "```"]


def main() -> None:
    out = ["## Buffer check", ""]
    if not KEY:
        out.append("**BUFFER_API_KEY is not set** as a repo secret.")
    else:
        code, d = gql("{ account { organizations { id name } } }")
        orgs = ((d.get("data") or {}).get("account") or {}).get("organizations") or []
        show(out, "Organizations", orgs)
        code, d = gql("{ __schema { queryType { fields { name args { name type { name kind ofType { name } } } } } } }")
        fields = (((d.get("data") or {}).get("__schema") or {}).get("queryType") or {}).get("fields") or []
        show(out, "Query fields (name + args)", [{"name": f["name"], "args": [(a["name"], (a["type"].get("name") or (a["type"].get("ofType") or {}).get("name"))) for a in f["args"]]} for f in fields])
        for o in orgs:
            for q in ('{ channels(input: {organizationId: "%s"}) { id name service } }' % o["id"],
                      '{ channels(input: {organizationId: "%s"}) { id name service isLocked } }' % o["id"]):
                code, d = gql(q)
                show(out, f"Channels of {o['name']}: `{q[:70]}...` -> HTTP {code}", d)
                if not d.get("errors"):
                    break
        for t in ("TikTokPostMetadataInput", "CreatePostInput"):
            show(out, f"Type {t}", type_info(t))
        post_input = type_info("CreatePostInput") or {}
        for f in post_input.get("inputFields") or []:
            tname = f["type"].get("name") or (f["type"].get("ofType") or {}).get("name")
            if f["name"] in ("mode", "schedulingType") and tname:
                show(out, f"Enum {tname} (for `{f['name']}`)", type_info(tname))
    open("buffer_report.md", "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out)[:3000])


if __name__ == "__main__":
    main()
