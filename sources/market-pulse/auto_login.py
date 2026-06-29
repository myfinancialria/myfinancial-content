"""Fyers daily login via TOTP — writes a fresh access_token.txt.

Adapted from fyers-bot/auto_login.py for headless CI use.

Required env:
  FYERS_CLIENT_ID, FYERS_SECRET, FYERS_REDIRECT,
  FYERS_FY_ID, FYERS_PIN, FYERS_TOTP_KEY
"""
from __future__ import annotations

import base64
import os
import sys
from urllib.parse import parse_qs, urlparse

import pyotp
import requests
from fyers_apiv3 import fyersModel

CLIENT_ID = os.environ["FYERS_CLIENT_ID"]
SECRET = os.environ["FYERS_SECRET"]
REDIRECT = os.environ["FYERS_REDIRECT"]
FY_ID = os.environ["FYERS_FY_ID"].strip().upper()
PIN = os.environ["FYERS_PIN"].strip()
TOTP_KEY = os.environ["FYERS_TOTP_KEY"].strip().replace(" ", "")

BASE = "https://api-t2.fyers.in/vagator/v2"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Origin": "https://login.fyers.in",
    "Referer": "https://login.fyers.in/",
    "Accept-Language": "en-US,en;q=0.9",
}


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _post(label: str, url: str, payload: dict, extra: dict | None = None) -> dict:
    r = requests.post(url, json=payload, headers={**HEADERS, **(extra or {})},
                      timeout=15)
    if r.status_code >= 400:
        sys.exit(f"[{label}] HTTP {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        sys.exit(f"[{label}] non-JSON response: {r.text[:300]}")


def main() -> int:
    # Sanity check TOTP key parses
    try:
        pyotp.TOTP(TOTP_KEY).now()
    except Exception as e:
        sys.exit(f"FYERS_TOTP_KEY invalid Base32: {e}")

    body1 = _post("send_login_otp", f"{BASE}/send_login_otp_v2",
                  {"fy_id": _b64(FY_ID), "app_id": "2"})
    req_key = body1.get("request_key")
    if not req_key:
        sys.exit(f"No request_key: {body1}")

    body2 = _post("verify_otp", f"{BASE}/verify_otp",
                  {"request_key": req_key, "otp": pyotp.TOTP(TOTP_KEY).now()})
    req_key2 = body2.get("request_key")
    if not req_key2:
        sys.exit(f"No request_key after verify_otp: {body2}")

    body3 = _post("verify_pin", f"{BASE}/verify_pin_v2",
                  {"request_key": req_key2, "identity_type": "pin",
                   "identifier": _b64(PIN)})
    short_token = body3.get("data", {}).get("access_token")
    if not short_token:
        sys.exit(f"No short_token after verify_pin: {body3}")

    app_id, app_type = CLIENT_ID.split("-")
    body4 = _post("get_auth_code", "https://api-t1.fyers.in/api/v3/token",
                  {
                      "fyers_id": FY_ID,
                      "app_id": app_id,
                      "redirect_uri": REDIRECT,
                      "appType": app_type,
                      "code_challenge": "",
                      "state": "ci",
                      "scope": "",
                      "nonce": "",
                      "response_type": "code",
                      "create_cookie": True,
                  },
                  extra={"Authorization": f"Bearer {short_token}"})

    url_field = body4.get("Url") or body4.get("url")
    if not url_field:
        sys.exit(f"No Url in get_auth_code response: {body4}")
    auth_code = parse_qs(urlparse(url_field).query).get("auth_code", [None])[0]
    if not auth_code:
        sys.exit(f"No auth_code in URL: {url_field}")

    session = fyersModel.SessionModel(
        client_id=CLIENT_ID, secret_key=SECRET, redirect_uri=REDIRECT,
        response_type="code", grant_type="authorization_code",
    )
    session.set_token(auth_code)
    resp = session.generate_token()
    if "access_token" not in resp:
        sys.exit(f"Token generation failed: {resp}")

    with open("access_token.txt", "w") as f:
        f.write(resp["access_token"])
    print("Fyers login successful, access_token.txt written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
