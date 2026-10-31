# Bangalore (Bengaluru) — Financial-Institution Leads from Free Resources

Extension of the **South_India_Financial_Leads** Google Sheet (23 May 2026): all Bangalore
results pulled from the free, official registries on its "Bulk Sources" tab, each with
location, phone number, email ID and website wherever the registry or the institution
publishes them. Compiled 4 September 2026. A small **Mangaluru** bonus section is included.

## What was pulled (full data files)

The raw registry exports are **deliberately not committed here** — this repo is public and
the exports contain thousands of individual distributors'/advisers' contact details. They
were delivered privately (Google Drive folder `Bangalore_Free_Resources_Leads` + chat
files), and every file can be regenerated in minutes with the two scripts in this folder:

| File | Source (free, official) | Rows | Fields |
|---|---|---|---|
| `amfi_mfd_bengaluru.csv` | AMFI "Locate a Distributor" registry — cities *Bangalore* + *Bengaluru*, de-duplicated | **4,866** (4,862 valid ARNs; 4,861 with email, 4,232 with phone) | ARN, name, address, PIN, phone (office/res), email, EUIN, KYD, ARN validity + status |
| `amfi_mfd_bengaluru_firms.csv` | Subset of the above — corporate/firm-style names only (Pvt/LLP/Advisors/Wealth/…) | **671** (all valid ARNs) | same |
| `amfi_mfd_mangaluru.csv` | AMFI registry — *Mangalore* + *Mangaluru* | **298** (all with email) | same |
| `sebi_ria_bengaluru.csv` | SEBI Recognised Intermediaries — **Investment Advisers** (intmId 13), location Bangalore/Bengaluru | **153** (151 with email, 114 with phone) | name, INA reg. no., email, phone, address, contact person, validity |
| `sebi_ra_bengaluru.csv` | SEBI — **Research Analysts** (intmId 14) | **149** (147 with email) | same, INH reg. nos. |
| `sebi_pms_bengaluru.csv` | SEBI — **Portfolio Managers** (intmId 33) | **38** (33 with email; some with website) | same, INP reg. nos. + website where filed |
| `sebi_ria_mangaluru.csv` | SEBI — Investment Advisers, Mangaluru | **2** | same |

Regenerate any of them:

```bash
cd leads/bangalore
python3 pull_amfi.py                             # AMFI MFD registry → CSVs
python3 pull_sebi.py 13 sebi_ria_bengaluru.csv IA Bangalore Bengaluru
python3 pull_sebi.py 14 sebi_ra_bengaluru.csv  RA Bangalore Bengaluru
python3 pull_sebi.py 33 sebi_pms_bengaluru.csv PMS Bangalore Bengaluru
```

### Registries that could NOT be bulk-pulled (manual routes)

- **NSE member directory** (nseindia.com/membership/find-a-broker) — bot-protected; filter
  by state = Karnataka in the browser and export. **BSE members**
  (bseindia.com/members/RegisteredMembers.html) — same, search by city in the browser.
  (SEBI's stock-broker registry location search matches almost nothing for Bangalore —
  brokers are registered per exchange, mostly against Mumbai correspondence addresses —
  so the verified anchor table below is the useful broker list.)
- **RBI list of NBFCs** (rbi.org.in → Database → NBFC list, `List_of_NBFCs_and_ARCs_registered_with_the_RBI.XLSX`)
  — rbidocs.rbi.org.in sits behind a JS challenge; download in a browser and filter the
  "Regional Office"/address columns for Karnataka. Note it carries **no phone/email/website**,
  only names + addresses.
- **RBI UCB lists / cooperatives.gov.in / DICGC insured banks** — PDF/portal routes as per
  the Bulk Sources tab; the verified Bengaluru co-op banks below were checked one by one
  against the banks' own sites instead.

## Verified anchor institutions — `bangalore_anchor_institutions.csv`

54 institutions verified one by one (4 Sep 2026) against their own websites / official
filings, in the same column layout as the South_India_Financial_Leads sheet: **50
Bengaluru** — 3 banks/SFBs (Canara, Ujjivan SFB, Jana SFB), 8 co-operative banks, 12
brokers/investment platforms (Zerodha, Groww, FYERS, Tradejini, Firstock, Alice Blue,
Way2Wealth, BgSE Financials, Fisdom, smallcase, Wint Wealth, GoldenPi), 15
NBFCs/HFCs/MFIs/digital lenders, 12 wealth/RIA/MFD/AMC firms — plus **4 Mangaluru**
(Karnataka Bank, SCDCC Bank, MCC Bank, Mangalore Co-op Town Bank).

### Best partnership fits first (they already run partner programs)

| Institution | Why |
|---|---|
| Zerodha | Authorised-Person + referral program (10% brokerage share) — partner@zerodha.com |
| FYERS | Formal "become a partner" AP program |
| Tradejini / Alice Blue / BgSE Financials | Published AP / franchise programs |
| Wealthy | Entire model is B2B2C onboarding of advisers/partners |
| Avanti Finance | Explicitly partner-led NBFC — partner onboarding page |
| Moneyview | Formal business-partner + digital-lead-partner programs |
| Rupeek | Business Partner + Sourcing Partner programs (gold loans) |
| Navi Finserv | Navi Lending Cloud co-lending platform |
| Way2Wealth | ~700-strong sub-broker/remisier network |

### Flags to respect before outreach

- **Under RBI directions (low priority):** Amanath Co-op Bank (to 12-Sep-2026), Sri Guru
  Raghavendra Sahakara Bank (AID since 2020, to 10-Nov-2026).
- **Merged / gone — not leads:** Fincare SFB → AU SFB (2024); National Co-op Bank
  Bangalore → Cosmos Bank (Jan 2025); Chaitanya India Fin Credit → Svatantra;
  ZestMoney wound down; Vijaya Bank → BoB; State Bank of Mysore → SBI; ING Vysya →
  Kotak; Corporation Bank → Union Bank.
- **Ownership changes:** axio → 100% Amazon (Sep 2025); Kuvera → CRED; Fisdom → Groww
  (Oct 2025); Way2Wealth → Shriram group (not Coffee Day); BSS Sonata = Kotak BC.
- **Leadership in flux:** Ujjivan SFB interim CEO Carol Furtado (Sep 2026); Canara Bank
  MD & CEO Brajesh Kumar Singh (Jun 2026); recheck names before addressing letters.
- **Not Bengaluru-HQ despite the vibe:** Paytm Money (Delhi regd/Mumbai corp), Upstox,
  Dhan, Angel One (Mumbai), INDmoney (Gurugram), slice SFB (Guwahati regd).
- **Referral-fee compliance:** since Aug 2024 (NSE circular), brokers may pay referral
  commissions only to exchange-registered Authorised Persons — structure broker deals
  as AP registrations, not plain referral fees.

## Compliance note (unchanged from the source sheet)

Every contact below and in the CSVs is an **official, published business channel** from an
official registry (AMFI/SEBI) or the institution's own website — nothing scraped from
private profiles, nothing invented. B2B outreach to published business contacts is fine;
bulk personal-mobile harvesting / unsolicited consumer messaging touches the DPDP Act 2023
and TRAI DND rules — keep outreach to business channels and honour opt-outs. Fields the
registry left blank are blank; "not published" means the institution does not publish one.
