#!/usr/bin/env python3
"""One-off API probe: what does GHL expose for Agent-Report-style metrics?
READ-ONLY. Prints findings to the workflow log. Safe to delete afterwards."""
import json, os, subprocess, urllib.parse, time
TOKEN=os.environ["GHL_PIT"]; LOC="3Nu5tCDlBMvA823iS8uy"
BASE="https://services.leadconnectorhq.com"

def call(url, label=""):
    p=subprocess.run(["curl","-s","-w","\n__H__%{http_code}",
        "-H",f"Authorization: Bearer {TOKEN}","-H","Version: 2021-07-28",
        "-H","Accept: application/json",url],capture_output=True,text=True)
    body,_,code=p.stdout.rpartition("__H__")
    return code.strip(), body.rstrip("\n")

print("="*70); print("1) CANDIDATE REPORTING ENDPOINTS")
for path in ["/reporting/agent","/reporting/calls","/conversations/reports",
             f"/locations/{LOC}/reporting", "/reporting/messages",
             f"/conversations/messages/statistics?locationId={LOC}",
             f"/emails/statistics?locationId={LOC}"]:
    c,b=call(BASE+path)
    print(f"  {path:55s} -> HTTP {c} {b[:90]}")

print("="*70); print("2) FULL MESSAGE OBJECT SHAPE (per type)")
c,b=call(f"{BASE}/conversations/search?locationId={LOC}&limit=25&sortBy=last_message_date&sort=desc")
convs=json.loads(b).get("conversations",[]) if c=="200" else []
seen={}
allkeys=set()
for cv in convs:
    c2,b2=call(f"{BASE}/conversations/{cv['id']}/messages?limit=100")
    if c2!="200": continue
    blk=json.loads(b2).get("messages",{})
    msgs=blk.get("messages",blk) if isinstance(blk,dict) else blk
    for m in msgs or []:
        allkeys.update(m.keys())
        t=m.get("messageType","?")
        if t not in seen:
            seen[t]=m
    if len(seen)>=5: break
print("  ALL KEYS SEEN ON MESSAGES:", sorted(allkeys))
for t,m in seen.items():
    print(f"\n  --- {t} (direction={m.get('direction')}) ---")
    print("   ", json.dumps({k:v for k,v in m.items() if k not in ("body","attachments")}, default=str)[:700])

print("="*70); print("3) STATUS VALUE DISTRIBUTION (delivered/failed etc.)")
from collections import Counter
st=Counter(); types=Counter()
for cv in convs[:15]:
    c2,b2=call(f"{BASE}/conversations/{cv['id']}/messages?limit=100")
    if c2!="200": continue
    blk=json.loads(b2).get("messages",{})
    msgs=blk.get("messages",blk) if isinstance(blk,dict) else blk
    for m in msgs or []:
        st[str(m.get("status"))]+=1; types[str(m.get("messageType"))]+=1
print("  status values:",dict(st))
print("  messageType values:",dict(types))

print("="*70); print("4) SINGLE-MESSAGE DETAIL ENDPOINT (richer fields?)")
anym=next(iter(seen.values()),None)
if anym and anym.get("id"):
    for path in [f"/conversations/messages/{anym['id']}",
                 f"/conversations/messages/{anym['id']}/status"]:
        c3,b3=call(BASE+path); print(f"  {path[:60]:60s} -> HTTP {c3} {b3[:220]}")
print("="*70); print("PROBE COMPLETE")
