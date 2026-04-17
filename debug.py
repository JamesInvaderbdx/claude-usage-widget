"""Teste les endpoints usage avec les bons UUIDs."""
import json, os
from curl_cffi import requests as curl

COOKIE_FILE = os.path.expanduser("~/.claude_widget_cookie.json")
with open(COOKIE_FILE) as f:
    d = json.load(f)

s = curl.Session(impersonate="chrome")
s.cookies.set("sessionKey",   d["sessionKey"],  domain="claude.ai")
s.cookies.set("cf_clearance", d["cf_clearance"], domain="claude.ai")

ORG  = "d1a64253-81d6-45fb-ada6-577558acf236"
USER = "5384c038-e7a1-4616-97a0-3f8b5bf908d3"

def get(url):
    print(f"\n{'='*55}\n{url}")
    try:
        r = s.get(url, timeout=15)
        print(f"status: {r.status_code}")
        if r.status_code == 200:
            try:    print(json.dumps(r.json(), indent=2)[:3000])
            except: print(r.text[:500])
        else:
            print(r.text[:150])
    except Exception as e:
        print(f"erreur: {e}")

BASE_ORG  = f"https://claude.ai/api/organizations/{ORG}"
BASE_USER = f"https://claude.ai/api/users/{USER}"

for path in [
    f"{BASE_ORG}/rate_limit_status",
    f"{BASE_ORG}/usage",
    f"{BASE_ORG}/limits",
    f"{BASE_ORG}/subscription",
    f"{BASE_ORG}/entitlements",
    f"{BASE_ORG}/members/{USER}/rate_limits",
    f"{BASE_ORG}/members/{USER}/usage",
    f"{BASE_USER}/rate_limit_status",
    f"{BASE_USER}/usage",
    "https://claude.ai/api/rate_limit_status",
    "https://claude.ai/api/usage",
]:
    get(path)

input("\nEntrée pour fermer...")
