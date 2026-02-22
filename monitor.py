#!/usr/bin/env python3
"""
Ubiquiti G6 Pro Entry stock monitor.
Checks the product page every run and triggers Twilio call + Telegram message.
"""

import os
import sys
import time
import random
import datetime
import requests
from twilio.rest import Client

# ── Configuration (set these as GitHub Actions secrets / env variables) ───────
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN  = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER = os.environ["TWILIO_FROM_NUMBER"]
YOUR_PHONE_NUMBER  = os.environ["YOUR_PHONE_NUMBER"]
TELEGRAM_TOKEN     = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]

PRODUCT_URL  = (
    "https://eu.store.ui.com/eu/en/category/door-access-readers"
    "/collections/doorbell-entry/products/uvc-g6-pro-entry"
    "?variant=uvc-g6-pro-entry"
)
PRODUCT_NAME        = "Ubiquiti G6 Pro Entry"
LOG_FILE            = "run-log.txt"
SANITY_STRING       = "UVC-G6-Pro-Entry"
OUT_OF_STOCK_SIGNAL = "back in stock emails"

JITTER_MIN_SECONDS = 5
JITTER_MAX_SECONDS = 55

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
]

# ── Logging ───────────────────────────────────────────────────────────────────

def now_utc() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def write_log(status: str, message: str):
    line = f"{now_utc()} | {status:<10} | {message}\n"
    print(line.strip())
    with open(LOG_FILE, "a") as f:
        f.write(line)


# ── Fetching ──────────────────────────────────────────────────────────────────

def fetch_page(url: str) -> str:
    user_agent = random.choice(USER_AGENTS)
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.Timeout:
        raise RuntimeError("Request timed out after 30s")
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Connection error: {e}")

    if response.status_code == 429:
        raise RuntimeError("HTTP 429 - rate limited / too many requests")
    if response.status_code == 403:
        raise RuntimeError("HTTP 403 - access forbidden (possibly IP-blocked)")
    if response.status_code >= 500:
        raise RuntimeError(f"HTTP {response.status_code} - server error")
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} - unexpected status")

    return response.text


def validate_page(html: str):
    if SANITY_STRING not in html:
        snippet = html[:300].replace("\n", " ").strip()
        raise RuntimeError(
            f"CAPTCHA or block page detected - '{SANITY_STRING}' not found. "
            f"Page starts with: {snippet!r}"
        )


def is_in_stock(html: str) -> bool:
    return OUT_OF_STOCK_SIGNAL not in html


# ── Alerts ────────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }, timeout=10)
    response.raise_for_status()
    print(f"  Telegram sent: {response.json()['result']['message_id']}")


def make_call(client: Client, message: str):
    twiml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" loop="3">
    Alert. Ubiquiti G6 Pro Entry is now in stock. Go buy it now.
  </Say>
</Response>"""
    call = client.calls.create(
        twiml=twiml,
        from_=TWILIO_FROM_NUMBER,
        to=YOUR_PHONE_NUMBER,
    )
    print(f"  Call initiated: {call.sid}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    jitter = random.randint(JITTER_MIN_SECONDS, JITTER_MAX_SECONDS)
    print(f"Sleeping {jitter}s (jitter) before fetching...")
    time.sleep(jitter)

    try:
        html = fetch_page(PRODUCT_URL)
        validate_page(html)
    except RuntimeError as e:
        error_msg = str(e)
        write_log("ERROR", error_msg)
        try:
            send_telegram(f"WARNING: Stock monitor ERROR\n{error_msg}\nCheck GitHub Actions for details.")
        except Exception as t_err:
            print(f"  Could not send Telegram error: {t_err}")
        sys.exit(1)

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    if is_in_stock(html):
        write_log("IN STOCK", "Add to Cart detected - alerts firing!")
        # Phone call via Twilio
        try:
            make_call(client, "")
        except Exception as e:
            print(f"  Call failed: {e}")
        # Telegram alert
        try:
            send_telegram(
                f"ALERT! {PRODUCT_NAME} is NOW IN STOCK!\n\n"
                f"Buy it here: {PRODUCT_URL}"
            )
        except Exception as e:
            print(f"  Telegram alert failed: {e}")
    else:
        write_log("OK", "Not in stock")

    # Send Telegram status after every run
    try:
        status = "IN STOCK - GO BUY NOW!" if is_in_stock(html) else "Not in stock yet"
        send_telegram(f"{now_utc()}\n{PRODUCT_NAME}\nStatus: {status}")
    except Exception as e:
        print(f"  Telegram status failed: {e}")


if __name__ == "__main__":
    main()
