#!/usr/bin/env python3
"""Pull AMFI 'Locate a Distributor' registry rows for given cities into CSVs."""
import csv, json, sys, time, urllib.request, urllib.parse
from datetime import date

BASE = "https://www.amfiindia.com/api/distributor-agent"
TODAY = date(2026, 9, 4)

def fetch(city, page, page_size):
    q = urllib.parse.urlencode({"strOpt": "ALL", "city": city, "search": "", "page": page, "pageSize": page_size})
    req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))

def clean(s):
    if s is None:
        return ""
    return " ".join(str(s).replace('"', " ").split())

def arn_status(valid_till):
    if not valid_till:
        return "validity not shown"
    d = valid_till[:10]
    try:
        y, m, dd = map(int, d.split("-"))
        return "valid" if date(y, m, dd) >= TODAY else f"EXPIRED {d}"
    except Exception:
        return "validity not shown"

def pull_cities(cities, out_csv):
    rows, seen = [], set()
    for city in cities:
        first = fetch(city, 1, 500)
        total = (first.get("meta") or {}).get("total", 0)
        pages = (first.get("meta") or {}).get("pageCount", 0)
        print(f"[{city}] total={total} pages={pages}", flush=True)
        data = list(first.get("data") or [])
        for p in range(2, pages + 1):
            data.extend(fetch(city, p, 500).get("data") or [])
            print(f"[{city}] page {p}/{pages} cum={len(data)}", flush=True)
        for r in data:
            key = (clean(r.get("ARN")), clean(r.get("ARNHolderName")).lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "ARN": clean(r.get("ARN")),
                "Name": clean(r.get("ARNHolderName")),
                "Address": clean(r.get("Address")),
                "City": clean(r.get("City")),
                "PIN": clean(r.get("Pin")),
                "Phone (office)": clean(r.get("TelephoneNumber_O")),
                "Phone (res)": clean(r.get("TelephoneNumber_R")),
                "Email": clean(r.get("Email")).lower(),
                "EUIN": clean(r.get("EUIN")),
                "KYD compliant": clean(r.get("KYDCompliant")),
                "ARN valid from": clean(r.get("ARNValidFrom"))[:10],
                "ARN valid till": clean(r.get("ARNValidTill"))[:10],
                "ARN status (as of 2026-09-04)": arn_status(r.get("ARNValidTill")),
            })
    rows.sort(key=lambda r: (r["ARN status (as of 2026-09-04)"] != "valid", r["Name"].lower()))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    valid = sum(1 for r in rows if r["ARN status (as of 2026-09-04)"] == "valid")
    with_email = sum(1 for r in rows if r["Email"])
    with_phone = sum(1 for r in rows if r["Phone (office)"] or r["Phone (res)"])
    print(f"WROTE {out_csv}: {len(rows)} unique rows | valid ARN: {valid} | with email: {with_email} | with phone: {with_phone}", flush=True)

if __name__ == "__main__":
    pull_cities(["Bangalore", "Bengaluru"], "amfi_mfd_bengaluru.csv")
    pull_cities(["Mangalore", "Mangaluru"], "amfi_mfd_mangaluru.csv")
