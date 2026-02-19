#!/usr/bin/env python3
"""
Ubiquiti G6 Pro Entry stock monitor.
Checks the product page every run and triggers Twilio alerts when in stock.
Designed to be run by GitHub Actions on a schedule.
"""

import os
import sys
import time
import random
import datetime
import requests
from twilio.rest import Client

# ── Configuration (set these as GitHub Actions secrets) ──────────────────────
TWILIO_ACCOUNT_SID   = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN    = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_FROM_NUMBER   = os.environ["TWILIO_FROM_NUMBER"]
YOUR_PHONE_NUMBER    = os.environ["YOUR_PHONE_NUMBER"]
TWILIO_WHATSAPP_FROM = "whatsapp:+14155238886"

PRODUCT_URL  = (
    "https://eu.store.ui.com/eu/en/category/door-access-readers"
    "/collections/doorbell-entry/products/uvc-g6-pro-entry"
    "?variant=uvc-g6-pro-entry"
)
PRODUCT_NAME      = "Ubiquiti G6 Pro Entry"
LOG_FILE          = "run-log.txt"
SANITY_STRING     = "UVC-G6-Pro-Entry"
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

def make_call(client: Client, message: str):
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice" loop="3">
    {message}. Go buy it now
  </Say>
</Response>"""
    call = client.calls.create(
        twiml=twiml,
        from_=TWILIO_FROM_NUMBER,
        to=YOUR_PHONE_NUMBER,
    )
    print(f"  Call initiated: {call.sid}")


def send_whatsapp(client: Client, message: str):
    msg = client.messages.create(
        body=message,
        from_=TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:{YOUR_PHONE_NUMBER}",
    )
    print(f"  WhatsApp sent: {msg.sid}")


def send_error_whatsapp(client: Client, error_message: str):
    msg = client.messages.create(
        body=(
            f"WARNING: Stock monitor ERROR - {PRODUCT_NAME}\n"
            f"{error_message}\n"
            f"Check GitHub Actions for details."
        ),
        from_=TWILIO_WHATSAPP_FROM,
        to=f"whatsapp:{YOUR_PHONE_NUMBER}",
    )
    print(f"  Error WhatsApp sent: {msg.sid}")


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
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            send_error_whatsapp(client, error_msg)
        except Exception as twilio_err:
            print(f"  Could not send error WhatsApp: {twilio_err}")
        sys.exit(1)

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    if is_in_stock(html):
        write_log("IN STOCK", "Add to Cart detected - alerts firing!")
        alert_message = (
            f"ALERT {PRODUCT_NAME} is NOW IN STOCK on the Ubiquiti EU store. "
            f"Go to the store immediately to buy it"
        )
        make_call(client, alert_message)

    else:
        write_log("OK", "Not in stock")

    # Send WhatsApp after every run regardless of stock status
    try:
        timestamp = now_utc()
        status = "IN STOCK - GO BUY NOW!" if is_in_stock(html) else "Not in stock yet"
        send_whatsapp(client, f"{timestamp}\n{PRODUCT_NAME}\nStatus: {status}")
    except Exception as e:
        print(f"  WhatsApp failed: {e}")


if __name__ == "__main__":
    main()
