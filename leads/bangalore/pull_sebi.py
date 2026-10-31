#!/usr/bin/env python3
"""Pull SEBI recognised-intermediary records (by intmId) for given locations into CSV."""
import csv, html, re, sys, time, urllib.parse, urllib.request

AJAX = "https://www.sebi.gov.in/sebiweb/ajax/other/getintmfpiinfo.jsp"

def post(intm_id, location, page):
    body = urllib.parse.urlencode({
        "nextValue": "1", "next": "n", "intmId": str(intm_id), "contPer": "", "name": "",
        "regNo": "", "email": "", "location": location, "exchange": "", "affiliate": "",
        "alp": "", "doDirect": str(page), "intmIds": "",
    }).encode()
    req = urllib.request.Request(AJAX, data=body, headers={
        "User-Agent": "Mozilla/5.0", "Content-Type": "application/x-www-form-urlencoded",
        "Referer": f"https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doRecognisedFpi=yes&intmId={intm_id}",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))

def parse(page_html):
    total = 0
    m = re.search(r"of\s+(\d+)\s+records", page_html)
    if m:
        total = int(m.group(1))
    mt = re.search(r"name='totalpage'\s+value=(\d+)", page_html)
    pages = int(mt.group(1)) if mt else 1
    records = []
    for block in re.split(r"<div class='fixed-table-body card-table'>", page_html)[1:]:
        pairs = re.findall(
            r"<div class='title'><span>([^<]*)</span></div><div class='value[^']*'><span>(.*?)</span></div>",
            block, re.S)
        rec = {}
        for k, v in pairs:
            v = html.unescape(re.sub(r"<[^>]+>", " ", v))
            rec[k.strip()] = " ".join(v.split())
        if rec:
            records.append(rec)
    return total, pages, records

def pull(intm_id, locations, out_csv, label):
    seen, rows, all_keys = set(), [], []
    for loc in locations:
        first = post(intm_id, loc, 0)
        total, pages, recs = parse(first)
        print(f"[{label}/{loc}] records={total} pages={pages}", flush=True)
        for p in range(1, pages):
            _, _, more = parse(post(intm_id, loc, p))
            recs.extend(more)
            print(f"[{label}/{loc}] page {p+1}/{pages} cum={len(recs)}", flush=True)
        for r in recs:
            key = r.get("Registration No.") or (r.get("Name", "") + r.get("Address", ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
            for k in r:
                if k not in all_keys:
                    all_keys.append(k)
    if not rows:
        print(f"[{label}] no rows; skipping {out_csv}", flush=True)
        return
    rows.sort(key=lambda r: r.get("Name", "").lower())
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys)
        w.writeheader()
        w.writerows(rows)
    print(f"WROTE {out_csv}: {len(rows)} unique rows | fields: {all_keys}", flush=True)

if __name__ == "__main__":
    intm_id = int(sys.argv[1]); out = sys.argv[2]; label = sys.argv[3]
    locs = sys.argv[4:] or ["Bangalore", "Bengaluru"]
    pull(intm_id, locs, out, label)
