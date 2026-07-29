#!/usr/bin/env python3
"""
Weekly sales report -> report.html (rendered to report.png by the workflow).
Shows the last COMPLETED Mon-Sun week vs the prior week. READ-ONLY against GHL.

Data source:
  - if GHL_PIT is set -> pull live from GHL
  - elif REPORT_LOCAL_OPPS is set -> load that opportunities json (for local testing)
Filtering uses lead-creation date, matching the dashboard & GHL Agent Report.
"""
import json, os, sys, subprocess, urllib.parse, time
from datetime import datetime, timezone, timedelta

LOC = os.environ.get("GHL_LOCATION_ID", "3Nu5tCDlBMvA823iS8uy")
PIPELINE = os.environ.get("GHL_PIPELINE_ID", "ixVHFltl4lSZRbzeIoJL")
BASE = "https://services.leadconnectorhq.com"
HERE = os.path.dirname(os.path.abspath(__file__))
DASH_URL = os.environ.get("DASH_URL", "https://ruthlesshobo.github.io/Pontoon-Dashboard/")
REPS = {"Matthew Ford": "tmnM3l9311q3M1AnExCf", "Bonnie Puntasecca": "0PRUgBISGklY6P1J4Gk9",
        "Alyssa Erspamer": "Bwvy1ZmK1ueaSml9492D", "Charity Byars": "bQI1XlzuGb6uMTxEqtCR"}
CF_CRUISE = "HTO96SRNXYudIOCw0bWK"; CF_PAX = "btzbFPFGh21U29ingYKT"
TOKEN = os.environ.get("GHL_PIT")


def get(url):
    for a in range(6):
        p = subprocess.run(["curl", "-s", "-w", "\n__H__%{http_code}",
            "-H", f"Authorization: Bearer {TOKEN}", "-H", "Version: 2021-07-28",
            "-H", "Accept: application/json", url], capture_output=True, text=True)
        body, _, code = p.stdout.rpartition("__H__")
        if code == "200":
            try: return json.loads(body.rstrip("\n"))
            except json.JSONDecodeError: pass
        time.sleep(min(2 ** a, 20))
    raise RuntimeError(f"GHL request failed ({code}): {url}")


def parse(s):
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError: return None

def cf(o, cid):
    for c in (o.get("customFields") or []):
        if c.get("id") == cid: return c.get("fieldValueArray") or c.get("fieldValueString")
    return None

def pax(o):
    v = cf(o, CF_PAX)
    try: return float(str(v).strip().split()[0].replace(",", "")) if v else None
    except (ValueError, IndexError): return None

def ctype(o):
    v = cf(o, CF_CRUISE)
    return (v[0] if v else "") if isinstance(v, list) else (v or "")


def load_opps():
    local = os.environ.get("REPORT_LOCAL_OPPS")
    if local:
        return json.load(open(local))
    out, after, aid, page = [], None, None, 0
    while True:
        q = {"location_id": LOC, "pipeline_id": PIPELINE, "limit": "100"}
        if after: q["startAfter"], q["startAfterId"] = after, aid
        d = get(f"{BASE}/opportunities/search?" + urllib.parse.urlencode(q))
        opps = d.get("opportunities", [])
        if not opps: break
        out.extend(opps); page += 1
        m = d.get("meta", {}); after, aid, tot = m.get("startAfter"), m.get("startAfterId"), m.get("total")
        if len(out) >= (tot or 0) or not after or page > 120: break
    return out


def last_week_bounds(now):
    monday_this = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = monday_this - timedelta(days=7)       # last week's Monday
    end = monday_this - timedelta(microseconds=1)  # last week's Sunday 23:59:59
    return start, end


def metrics(opps, start, end, rep_uid=None, priv=False):
    def inb(o):
        d = parse(o.get("createdAt"));
        if not (d and start <= d <= end): return False
        if rep_uid is not None and o.get("assignedTo") != rep_uid: return False
        if priv and ctype(o) != "Private Cruise": return False
        return True
    S = [o for o in opps if inb(o)]
    won = [o for o in S if o.get("status") == "won"]
    lost = [o for o in S if o.get("status") in ("lost", "abandoned")]
    rev = sum(float(o.get("monetaryValue") or 0) for o in won)
    px = [pax(o) for o in S]; px = [p for p in px if p]
    return {"n": len(S), "won": len(won), "lost": len(lost), "rev": rev,
            "conv": (len(won) / (len(won) + len(lost)) * 100) if (len(won) + len(lost)) else 0,
            "avgPax": (sum(px) / len(px)) if px else 0}


def wow(cur, prev):
    if prev in (0, None): return '<span style="color:#8a98ab">–</span>'
    d = (cur - prev) / prev * 100
    up = d >= 0
    return f'<span style="color:{"#16a34a" if up else "#dc2626"};font-weight:700">{"▲" if up else "▼"} {abs(d):.0f}%</span>'

def money(n): return "$" + format(round(n), ",")


def build_html(opps, now):
    start, end = last_week_bounds(now)
    pstart, pend = start - timedelta(days=7), start - timedelta(microseconds=1)
    mLbl = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    span = f"{mLbl[start.month-1]} {start.day} – {mLbl[end.month-1]} {end.day}, {end.year}"

    tot = metrics(opps, start, end); ptot = metrics(opps, pstart, pend)
    priv = metrics(opps, start, end, priv=True); ppriv = metrics(opps, pstart, pend, priv=True)

    def kpi(label, val, cur, prev, gold=False):
        return f'''<td style="padding:0 6px;width:25%;vertical-align:top">
          <div style="background:#fff;border:1px solid #e4e9f1;border-radius:12px;padding:16px 18px">
            <div style="font-size:11px;letter-spacing:.5px;text-transform:uppercase;color:#63748b;font-weight:700">{label}</div>
            <div style="font-size:30px;font-weight:800;color:{'#b57614' if gold else '#16202e'};margin-top:6px;line-height:1">{val}</div>
            <div style="font-size:12px;color:#8a98ab;margin-top:8px">{wow(cur,prev)} <span style="color:#8a98ab">vs prior week</span></div>
          </div></td>'''

    reprows = ""
    ranked = sorted(REPS.items(), key=lambda kv: -metrics(opps, start, end, kv[1])["rev"])
    palette = {"Matthew Ford":"#0f7d6b","Bonnie Puntasecca":"#b57614","Alyssa Erspamer":"#3b6fd4","Charity Byars":"#8b3fc4"}
    for name, uid in ranked:
        m = metrics(opps, start, end, uid); pm = metrics(opps, pstart, pend, uid)
        ini = "".join(w[0] for w in name.split()[:2])
        reprows += f'''<tr>
          <td style="padding:11px 12px;border-bottom:1px solid #eef2f7">
            <table cellpadding="0" cellspacing="0"><tr>
              <td style="width:28px"><div style="width:26px;height:26px;border-radius:50%;background:{palette[name]};color:#fff;text-align:center;line-height:26px;font-size:11px;font-weight:700">{ini}</div></td>
              <td style="padding-left:9px;font-weight:600;color:#16202e">{name}</td></tr></table></td>
          <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;text-align:right;font-weight:600">{m['n']}</td>
          <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;text-align:right">{m['won']}</td>
          <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;text-align:right"><span style="background:{'#dcefe9' if m['conv']>=40 else '#f6ecd8'};color:{'#0f7d6b' if m['conv']>=40 else '#b57614'};font-weight:700;padding:2px 9px;border-radius:20px;font-size:12px">{m['conv']:.0f}%</span></td>
          <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;text-align:right;font-weight:700">{money(m['rev'])}</td>
          <td style="padding:11px 12px;border-bottom:1px solid #eef2f7;text-align:right;font-size:12px">{wow(m['rev'],pm['rev'])}</td>
        </tr>'''

    html = f'''<!doctype html><html><head><meta charset="utf-8"><style>
      *{{margin:0;padding:0;box-sizing:border-box}}
      body{{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#eef1f6}}
    </style></head><body>
    <div style="width:960px;background:#eef1f6;padding:26px 28px">
      <table cellpadding="0" cellspacing="0" style="width:100%"><tr>
        <td><table cellpadding="0" cellspacing="0"><tr>
          <td><div style="width:40px;height:40px;border-radius:10px;background:#0f7d6b;color:#fff;text-align:center;line-height:40px;font-size:20px">⚓</div></td>
          <td style="padding-left:12px"><div style="font-size:20px;font-weight:800;color:#0e2438">Pontoon Saloon — Weekly Sales Report</div>
            <div style="font-size:13px;color:#63748b">Week of {span} · vs the week before</div></td></tr></table></td>
        <td style="text-align:right;color:#8a98ab;font-size:12px">Nashville, TN<br>Sales Pipeline · read-only from GoHighLevel</td>
      </tr></table>

      <table cellpadding="0" cellspacing="0" style="width:100%;margin-top:20px"><tr>
        {kpi("New Leads", tot['n'], tot['n'], ptot['n'])}
        {kpi("Won", tot['won'], tot['won'], ptot['won'])}
        {kpi("Revenue", money(tot['rev']), tot['rev'], ptot['rev'], gold=True)}
        {kpi("Conversion", f"{tot['conv']:.0f}%", tot['conv'], ptot['conv'])}
      </tr></table>

      <table cellpadding="0" cellspacing="0" style="width:100%;margin-top:16px">
        <tr><td style="background:#0e2438;border-radius:12px 12px 0 0;padding:13px 18px;color:#fff;font-weight:700;font-size:14px">⛵ Private Cruise this week</td></tr>
        <tr><td style="background:#fff;border:1px solid #e4e9f1;border-top:0;border-radius:0 0 12px 12px;padding:14px 18px">
          <table cellpadding="0" cellspacing="0" style="width:100%"><tr>
            <td style="width:25%"><span style="color:#63748b;font-size:12px">Leads</span><br><b style="font-size:20px">{priv['n']}</b> <span style="font-size:12px">{wow(priv['n'],ppriv['n'])}</span></td>
            <td style="width:25%"><span style="color:#63748b;font-size:12px">Won</span><br><b style="font-size:20px">{priv['won']}</b></td>
            <td style="width:25%"><span style="color:#63748b;font-size:12px">Revenue</span><br><b style="font-size:20px;color:#b57614">{money(priv['rev'])}</b> <span style="font-size:12px">{wow(priv['rev'],ppriv['rev'])}</span></td>
            <td style="width:25%"><span style="color:#63748b;font-size:12px">Avg PAX</span><br><b style="font-size:20px">{priv['avgPax']:.0f}</b></td>
          </tr></table></td></tr>
      </table>

      <table cellpadding="0" cellspacing="0" style="width:100%;margin-top:16px;background:#fff;border:1px solid #e4e9f1;border-radius:12px">
        <tr><td colspan="6" style="padding:14px 16px 4px;font-weight:700;font-size:14px;color:#16202e">Rep productivity — this week</td></tr>
        <tr style="font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:#63748b">
          <td style="padding:6px 12px">Rep</td><td style="padding:6px 12px;text-align:right">Leads</td>
          <td style="padding:6px 12px;text-align:right">Won</td><td style="padding:6px 12px;text-align:right">Conv.</td>
          <td style="padding:6px 12px;text-align:right">Revenue</td><td style="padding:6px 12px;text-align:right">WoW $</td></tr>
        {reprows}
      </table>

      <table cellpadding="0" cellspacing="0" style="width:100%;margin-top:18px"><tr>
        <td><a href="{DASH_URL}" style="background:#0f7d6b;color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:12px 22px;border-radius:9px;display:inline-block">Open the live dashboard →</a></td>
        <td style="text-align:right;color:#8a98ab;font-size:11px">Numbers reconcile with GHL's Agent Report · refreshed hourly<br>Messaging activity (SMS/email/calls) lives in GHL's Agent Report</td>
      </tr></table>
    </div></body></html>'''
    return html, span


def main():
    now = datetime.now(timezone.utc)
    # allow a fixed "now" for testing
    if os.environ.get("REPORT_NOW"):
        now = datetime.fromisoformat(os.environ["REPORT_NOW"]).replace(tzinfo=timezone.utc)
    opps = load_opps()
    html, span = build_html(opps, now)
    open(os.path.join(HERE, "report.html"), "w").write(html)
    print(f"Built report.html for week of {span} ({len(opps)} opps scanned)", file=sys.stderr)


if __name__ == "__main__":
    main()
