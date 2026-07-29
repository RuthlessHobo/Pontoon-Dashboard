#!/usr/bin/env python3
"""
Pontoon Saloon sales dashboard — data refresh + build.

READ-ONLY against GoHighLevel. Pulls users + all Sales Pipeline opportunities,
computes a compact per-opportunity dataset, and injects it into the dashboard
template to produce dashboard.html.

Auth: the GHL Private Integration Token is read from the GHL_PIT environment
variable. It is NEVER hardcoded or written to disk. Do not commit a token.

Usage:  GHL_PIT=pit-xxxx python3 refresh.py
Output: dashboard.html  (self-contained, data baked in)
"""
import json, os, sys, subprocess, urllib.parse, time
from datetime import datetime, timezone

TOKEN = os.environ.get("GHL_PIT")
if not TOKEN:
    sys.exit("ERROR: set GHL_PIT env var to the GHL Private Integration Token (read-only use).")

LOC = os.environ.get("GHL_LOCATION_ID", "3Nu5tCDlBMvA823iS8uy")   # Pontoon Saloon
PIPELINE = os.environ.get("GHL_PIPELINE_ID", "ixVHFltl4lSZRbzeIoJL")  # 1 - Sales Pipeline
BASE = "https://services.leadconnectorhq.com"
HERE = os.path.dirname(os.path.abspath(__file__))

CF_CRUISE = "HTO96SRNXYudIOCw0bWK"
CF_PAX = "btzbFPFGh21U29ingYKT"
STAGE_IDX = {
    "978be413-e86a-414d-914d-1593086a1728": 0, "5f37a560-f3bb-453b-ad67-cb55bb95660e": 1,
    "0a624108-542f-4cef-89e9-f535cae75b8f": 2, "55993118-ef76-4b07-968b-11c60a1773c2": 3,
    "818d36d2-42fe-469f-b828-706b4b31034e": 4, "fbab6367-d76c-442d-be5b-f3de0e0b4ec5": 5,
    "10e4862c-856a-4051-8e27-5c6e63821aef": 6,
}
REP_NAMES = ["Matthew Ford", "Bonnie Puntasecca", "Alyssa Erspamer", "Charity Byars"]


def get(url):
    """GET with retry on rate-limit (429) / server errors. Body and HTTP status are
    separated by a sentinel so we never mistake a 429 error body for real data."""
    last = ""
    for attempt in range(6):
        p = subprocess.run(
            ["curl", "-s", "-w", "\n__HTTP__%{http_code}",
             "-H", f"Authorization: Bearer {TOKEN}",
             "-H", "Version: 2021-07-28", "-H", "Accept: application/json", url],
            capture_output=True, text=True)
        body, _, code = p.stdout.rpartition("__HTTP__")
        body = body.rstrip("\n")
        last = code
        if code == "200":
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                pass
        # 429 rate limit / 5xx / transient -> back off and retry
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"GHL request failed after retries (last HTTP {last}): {url}")


def ms(s):
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def cf(o, cid):
    for c in (o.get("customFields") or []):
        if c.get("id") == cid:
            return c.get("fieldValueArray") or c.get("fieldValueString")
    return None


def pax(o):
    v = cf(o, CF_PAX)
    if v is None:
        return None
    try:
        return float(str(v).strip().split()[0].replace(",", ""))
    except (ValueError, IndexError):
        return None


def ctype(o):
    v = cf(o, CF_CRUISE)
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def pull_users():
    d = get(f"{BASE}/users/?locationId={LOC}")
    return {u["id"]: u.get("name") for u in d.get("users", [])}


def pull_opps():
    out, after, after_id, page = [], None, None, 0
    while True:
        q = {"location_id": LOC, "pipeline_id": PIPELINE, "limit": "100"}
        if after:
            q["startAfter"], q["startAfterId"] = after, after_id
        d = get(f"{BASE}/opportunities/search?" + urllib.parse.urlencode(q))
        opps = d.get("opportunities", [])
        if not opps:
            break
        out.extend(opps)
        page += 1
        meta = d.get("meta", {})
        after, after_id, total = meta.get("startAfter"), meta.get("startAfterId"), meta.get("total")
        print(f"  opps page {page}: {len(out)}/{total}", file=sys.stderr)
        if len(out) >= (total or 0) or not after or page > 120:
            break
    return out


def build_compact(opps, users):
    rows = []
    for o in opps:
        c = ms(o.get("createdAt"))
        rows.append({
            "c": c, "s": ms(o.get("lastStatusChangeAt")) or c,
            "st": (o.get("status") or "open")[0],
            "v": round(float(o.get("monetaryValue") or 0), 2),
            "r": users.get(o.get("assignedTo"), "") if o.get("assignedTo") else "",
            "ct": ctype(o), "p": pax(o), "sg": STAGE_IDX.get(o.get("pipelineStageId")),
        })
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"data_through": today, "reps": REP_NAMES, "rows": rows}


def main():
    print("Pulling users...", file=sys.stderr)
    users = pull_users()
    print(f"  {len(users)} users", file=sys.stderr)
    print("Pulling opportunities...", file=sys.stderr)
    opps = pull_opps()
    print(f"  {len(opps)} opportunities", file=sys.stderr)

    compact = build_compact(opps, users)

    # optional activity.json (produced by the separate, heavier activity.py job)
    act = "null"
    apath = os.path.join(HERE, "activity.json")
    if os.path.exists(apath):
        a = json.load(open(apath))
        if a.get("complete"):
            act = json.dumps(a)

    tpl = open(os.path.join(HERE, "dashboard_template.html")).read()
    html = tpl.replace("__COMPACT__", json.dumps(compact)).replace("__ACTIVITY__", act)
    logo = os.path.join(HERE, "logo_white.png")
    if "__LOGO_WHITE__" in html and os.path.exists(logo):
        import base64
        html = html.replace("__LOGO_WHITE__",
            "data:image/png;base64," + base64.b64encode(open(logo, "rb").read()).decode())
    out = os.path.join(HERE, "dashboard.html")
    open(out, "w").write(html)
    print(f"Built {out} ({len(html)} bytes) | rows={len(compact['rows'])} "
          f"| activity={'included' if act != 'null' else 'none'}", file=sys.stderr)


if __name__ == "__main__":
    main()
