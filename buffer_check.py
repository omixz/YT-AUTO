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


def main() -> None:
    out = ["## Buffer check", ""]
    if not KEY:
        out.append("**BUFFER_API_KEY is not set** as a repo secret. Create a Buffer account, connect TikTok, make an API key, and add it as the secret `BUFFER_API_KEY`.")
    else:
        candidates = [
            "{ account { organizations { id name channels { id name service } } } }",
            "{ account { organizations { id name } } }",
            "{ channels { id name service } }",
        ]
        for q in candidates:
            code, data = gql(q)
            out += [f"### `{q}` -> HTTP {code}", "```json", json.dumps(data, indent=1)[:2500], "```"]
            if code == 200 and not data.get("errors"):
                break
        code, data = gql('{ __type(name: "PostInputMetaData") { inputFields { name type { name kind } } } }')
        out += ["### Platform metadata accepted by createPost", "```json", json.dumps(data, indent=1)[:1500], "```"]
        code, data = gql('{ __type(name: "TiktokPostMetadataInput") { inputFields { name type { name kind } } } }')
        out += ["### TikTok metadata fields", "```json", json.dumps(data, indent=1)[:1500], "```"]
    pid = os.environ.get("POST_ID", "").strip()
    if KEY and pid:
        t = type_info("Post") or {}
        code, d = gql('{ __type(name: "Post") { fields { name type { name kind ofType { name kind } } } } }')
        fields = ((d.get("data") or {}).get("__type") or {}).get("fields") or []
        def leaf(f):
            t_ = f["type"]; return (t_.get("kind") == "SCALAR" or t_.get("kind") == "ENUM") or ((t_.get("ofType") or {}).get("kind") in ("SCALAR", "ENUM"))
        wanted = [f["name"] for f in fields if leaf(f)][:40]
        show(out, "Post scalar fields available", wanted)
        code, d = gql('{ post(input: {id: "%s"}) { %s } }' % (pid, " ".join(wanted)))
        show(out, f"Status of post {pid}", d)
    open("buffer_report.md", "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out)[:3000])


if __name__ == "__main__":
    main()
