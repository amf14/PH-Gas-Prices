"""
PH Gas Prices Scraper
Scrapes DOE price monitoring page and updates GitHub Gist with latest prices.
Run this via GitHub Actions every Tuesday at 10am Manila time.
"""

import json
import re
import os
from datetime import datetime, date
import requests
from bs4 import BeautifulSoup

# ── Config ─────────────────────────────────────────────────────────────────
GIST_ID = os.environ["GIST_ID"]           # your GitHub Gist ID
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"] # GitHub personal access token
GIST_FILENAME = "ph_gas_data.json"

DOE_URL = "https://www.doe.gov.ph/price-monitoring-charts?q=retail-pump-prices-metro-manila"
FALLBACK_URL = "https://legacy.doe.gov.ph/oil-monitor"

# ── Fetch DOE page ──────────────────────────────────────────────────────────
def fetch_prices():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GasPriceScraper/1.0)"}

    # Try the main price monitoring page first
    resp = requests.get(DOE_URL, headers=headers, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for a table with price data
    tables = soup.find_all("table")
    prices = {}

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            text = " ".join(cells).lower()

            if "ron 91" in text or "regular" in text:
                prices["ron91"] = extract_price(cells)
            elif "ron 95" in text or "premium" in text:
                prices["ron95"] = extract_price(cells)
            elif "ron 97" in text or "super" in text:
                prices["ron97"] = extract_price(cells)
            elif "diesel" in text:
                prices["diesel"] = extract_price(cells)
            elif "kerosene" in text:
                prices["kerosene"] = extract_price(cells)

    return prices


def extract_price(cells):
    """Extract min, max, avg from a row of cells."""
    nums = []
    for cell in cells:
        # Match price-like numbers e.g. 56.20
        matches = re.findall(r"\d{2,3}\.\d{2}", cell)
        nums.extend([float(m) for m in matches])

    nums = sorted(set(nums))
    if len(nums) >= 2:
        return {
            "min": f"{min(nums):.2f}",
            "max": f"{max(nums):.2f}",
            "avg": f"{sum(nums)/len(nums):.2f}"
        }
    elif len(nums) == 1:
        return {"min": f"{nums[0]:.2f}", "max": f"{nums[0]:.2f}", "avg": f"{nums[0]:.2f}"}
    return None


# ── Load previous data from Gist ────────────────────────────────────────────
def load_previous_data():
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        content = resp.json()["files"][GIST_FILENAME]["content"]
        return json.loads(content)
    return None


def compute_change(new_avg, old_avg):
    """Return change amount and direction."""
    if old_avg is None:
        return "0.00", "same"
    diff = float(new_avg) - float(old_avg)
    if diff > 0.005:
        return f"+{diff:.2f}", "up"
    elif diff < -0.005:
        return f"{diff:.2f}", "down"
    return "0.00", "same"


# ── Build JSON payload ──────────────────────────────────────────────────────
def build_payload(prices, previous):
    today = date.today()
    # DOE effectivity week: Tuesday to Monday
    week_start = today.strftime("%b %d")
    week_end_day = today.replace(day=today.day + 6)
    week_end = week_end_day.strftime("%b %d, %Y")
    week_label = f"{week_start} – {week_end}"

    fuel_map = [
        ("ron91",    "Ron 91",    "Regular"),
        ("ron95",    "Ron 95",    "Premium"),
        ("ron97",    "Ron 97+",   "Super"),
        ("diesel",   "Diesel",    "Auto"),
        ("kerosene", "Kerosene",  "Household"),
    ]

    fuels = []
    for key, name, grade in fuel_map:
        p = prices.get(key)
        if not p:
            # fallback to previous data if scrape missed it
            if previous:
                prev_fuel = next((f for f in previous.get("fuels", []) if f["name"] == name), None)
                if prev_fuel:
                    p = {"min": prev_fuel["min"], "max": prev_fuel["max"], "avg": prev_fuel["avg"]}

        if not p:
            continue

        old_avg = None
        if previous:
            prev_fuel = next((f for f in previous.get("fuels", []) if f["name"] == name), None)
            if prev_fuel:
                old_avg = prev_fuel["avg"]

        change, direction = compute_change(p["avg"], old_avg)

        fuels.append({
            "name": name,
            "grade": grade,
            "min": p["min"],
            "max": p["max"],
            "avg": p["avg"],
            "change": change,
            "direction": direction
        })

    return {
        "week": week_label,
        "updated": today.strftime("%b %d, %Y"),
        "region": "NCR Metro Manila",
        "source": "DOE Oil Monitor",
        "crude_wti": "0.00",   # optional: wire up a free API like EIA or Alpha Vantage
        "crude_change": "N/A",
        "fuels": fuels
    }


# ── Update Gist ─────────────────────────────────────────────────────────────
def update_gist(payload):
    url = f"https://api.github.com/gists/{GIST_ID}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    body = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(payload, indent=2)
            }
        }
    }
    resp = requests.patch(url, headers=headers, json=body)
    if resp.status_code == 200:
        print(f"✅ Gist updated successfully: {payload['updated']}")
    else:
        print(f"❌ Gist update failed: {resp.status_code} {resp.text}")


# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🔍 Fetching DOE prices...")
    prices = fetch_prices()
    print(f"   Found: {list(prices.keys())}")

    print("📂 Loading previous data from Gist...")
    previous = load_previous_data()

    print("🔧 Building payload...")
    payload = build_payload(prices, previous)

    print("📤 Updating Gist...")
    update_gist(payload)
