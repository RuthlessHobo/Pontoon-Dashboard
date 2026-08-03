#!/usr/bin/env python3
"""
Rep activity pull — counts OUTBOUND messages (calls / SMS / emails) by user, per day,
from the GHL Conversations feed. READ-ONLY.

This is HEAVY: Pontoon Saloon has ~40k conversations in an 8-week window (high-volume
SMS). Run it on a DAILY (not hourly) schedule, or scoped to a short rolling window.
Writes activity.json, which refresh.py picks up if complete.

Auth: GHL_PIT env var (never hardcoded). Window via ACT_START / ACT_END (YYYY-MM-DD).
Usage: GHL_PIT=pit-xxxx ACT_START=2026-06-01 ACT_END=2026-07-27 python3 activity.py
"""
import json, os, sys, subprocess, urllib.parse, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

TOKEN = os.environ.get("GHL_PIT")
if not TOKEN:
    sys.exit("ERROR: set GHL_PIT env var (read-only use).")
LOC = os.environ.get("GHL_LOCATION_ID", "3Nu5tCDlBMvA823iS8uy")
BASE = "https://services.leadconnectorhq.com"
HERE = os.path.dirname(os.path.abspath(__file__))
START = os.environ.get("ACT_START", "2026-06-01")
END = os.environ.get("ACT_END", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
CUTOFF = datetime.fromisoformat(START).replace(tzinfo=timezone.utc)
CUTOFF_MS = int(CUTOFF.timestamp() * 1000)
WORKERS = int(os.environ.get("ACT_WORKERS", "6"))
BUDGET_MIN = int(os.environ.get("ACT_BUDGET_MIN", "280"))  # stop before Actions 6h limit


def curl(url):
    for a in range(6):
        p = subprocess.run(["curl", "-s", "-w", "\n__HTTP__%{http_code}",
                            "-H", f"Authorization: Bearer {TOKEN}",
                            "-H", "Version: 2021-07-28", "-H", "Accept: application/json", url],
                           capture_output=True, text=True)
        body, _, code = p.stdout.rpartition("__HTTP__")
        if code == "200":
            try:
                return json.loads(body.rstrip("\n"))
            except json.JSONDecodeError:
                pass
        time.sleep(min(2 ** a, 20))   # back off on 429 / 5xx
    return {}


def users_map():
    d = curl(f"{BASE}/users/?locationId={LOC}")
    return {u["id"]: u.get("name") for u in d.get("users", [])}


def collect_convs():
    ids, after, pages = [], None, 0
    while True:
        q = {"locationId": LOC, "limit": "100", "sortBy": "last_message_date", "sort": "desc"}
        if after:
            q["startAfterDate"] = after
        d = curl(f"{BASE}/conversations/search?" + urllib.parse.urlencode(q))
        cs = d.get("conversations", [])
        if not cs:
            break
        stop = False
        for c in cs:
            if (c.get("lastMessageDate") or 0) < CUTOFF_MS:
                stop = True
                break
            ids.append(c["id"])
        pages += 1
        after = cs[-1].get("lastMessageDate")
        if pages % 20 == 0:
            print(f"  [collect] {len(ids)} convs", file=sys.stderr)
        if stop or not after or pages > 800:
            break
    return ids


def cat(mt):
    mt = (mt or "").upper()
    if "CALL" in mt:
        return "call"
    if mt == "TYPE_SMS":
        return "sms"
    if mt == "TYPE_EMAIL":
        return "email"
    return "other"


def conv_msgs(cid):
    out, last, hops = [], None, 0
    while hops < 4:
        url = f"{BASE}/conversations/{cid}/messages?limit=100" + (f"&lastMessageId={last}" if last else "")
        d = curl(url)
        block = d.get("messages", {})
        msgs = block.get("messages", block) if isinstance(block, dict) else block
        if not msgs:
            break
        older_in = True
        for m in msgs:
            da = m.get("dateAdded")
            if not da:
                continue
            try:
                dt = datetime.fromisoformat(da.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt < CUTOFF:
                older_in = False
                continue
            if m.get("direction") == "outbound" and m.get("userId"):
                out.append((m["userId"], dt.strftime("%Y-%m-%d"), cat(m.get("messageType"))))
        if len(msgs) < 100 or not older_in:
            break
        last, hops = msgs[-1].get("id"), hops + 1
    return out


def blank():
    return {"call": 0, "sms": 0, "email": 0, "other": 0}


def aggregate(events, users):
    by_rep = {}
    for uid, day, c in events:
        r = by_rep.setdefault(uid, {"name": users.get(uid, uid), "totals": blank(), "by_day": {}})
        r["totals"][c] += 1
        r["by_day"].setdefault(day, blank())[c] += 1
    return by_rep


def save(by_rep, n, complete):
    json.dump({"window": {"start": START, "end": END}, "conversations_processed": n,
               "complete": complete, "by_rep": by_rep},
              open(os.path.join(HERE, "activity.json"), "w"), indent=1)


def main():
    t0 = time.time()
    users = users_map()
    print(f"collecting conversations since {START}...", file=sys.stderr)
    ids = collect_convs()
    print(f"  {len(ids)} conversations in window", file=sys.stderr)
    events, done, timed_out = [], 0, False
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for res in ex.map(conv_msgs, ids):
            events.extend(res)
            done += 1
            if done % 1000 == 0:
                save(aggregate(events, users), done, False)
                mins = (time.time() - t0) / 60
                print(f"  [msgs] {done}/{len(ids)}  {mins:.0f}m elapsed", file=sys.stderr)
                if mins > BUDGET_MIN:
                    timed_out = True
                    print(f"  [msgs] time budget {BUDGET_MIN}m reached - stopping early", file=sys.stderr)
                    break
    by_rep = aggregate(events, users)
    save(by_rep, done, not timed_out)
    print(f"{'PARTIAL' if timed_out else 'DONE'}: {done}/{len(ids)} convs, {len(events)} outbound rep messages",
          file=sys.stderr)

    # --- verification: print June per-rep totals to compare against GHL's Agent Report ---
    print("VERIFY (compare to GHL Agent Report, manual sends only):", file=sys.stderr)
    for name in ("Matthew Ford", "Bonnie Puntasecca", "Alyssa Erspamer", "Charity Byars"):
        rep = next((r for r in by_rep.values() if r["name"] == name), None)
        if not rep:
            print(f"  {name:22s} no activity", file=sys.stderr); continue
        c = s_ = e = 0
        for day, v in rep["by_day"].items():
            if day.startswith("2026-06"):
                c += v["call"]; s_ += v["sms"]; e += v["email"]
        print(f"  {name:22s} JUNE calls={c} sms={s_} email={e}", file=sys.stderr)


if __name__ == "__main__":
    main()
