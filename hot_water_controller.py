import os
import json
import requests
from datetime import datetime, timedelta
import pytz

# import keys

# Telegram config from env
BOT_TOKEN = os.environ["HOT_SWITCH_BOT_TOKEN"]
CHANNEL_ID = os.environ["AUTOMATIONS_CHANNEL_ID"]

# BOT_TOKEN = keys.HOT_SWITCH_BOT_TOKEN
# CHANNEL_ID = keys.AUTOMATIONS_CHAT_ID

tz = pytz.timezone("Europe/London")
PRODUCT_CODE = "AGILE-24-10-01"
REGION_CODE = "M"
TARIFF_CODE = f"E-1R-{PRODUCT_CODE}-{REGION_CODE}"

def get_prices():
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    url = (
        f"https://api.octopus.energy/v1/products/{PRODUCT_CODE}/"
        f"electricity-tariffs/{TARIFF_CODE}/standard-unit-rates/"
        f"?period_from={today}T00:00Z&period_to={tomorrow}T00:00Z"
    )

    r = requests.get(url)
    r.raise_for_status()
    data = r.json()["results"]
    return sorted([
        {
            "start": datetime.fromisoformat(p["valid_from"].replace("Z", "+00:00")).astimezone(tz),
            "end": datetime.fromisoformat(p["valid_to"].replace("Z", "+00:00")).astimezone(tz),
            "price": p["value_inc_vat"]
        } for p in data
    ], key=lambda x: x["start"])

def find_cheapest_block(prices, start_hour, end_hour):
    window = [p for p in prices if start_hour <= p["start"].hour < end_hour]
    if len(window) < 4:
        return None
    best = min((window[i:i+4] for i in range(len(window)-3)),
               key=lambda b: sum(p["price"] for p in b))
    return best

def format_msg(label, block):
    start = block[0]["start"].strftime("%H:%M")
    end = block[-1]["end"].strftime("%H:%M")
    total = sum(p["price"] for p in block)
    return (
        f"⚡️ Cheapest {label} block\n"
        f"🕒 {start} - {end}\n"
        f"💷 Total: {total:.2f}p"
    )

def send_telegram_message(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": msg, "parse_mode": "Markdown"}
    r = requests.post(url, data=payload)
    if not r.ok:
        print(f"⚠️ Telegram failed: {r.text}")

def save_schedule(blocks):
    with open("schedule.json", "w") as f:
        json.dump({
            "messages": [
                {"time": b[0]["start"].strftime("%Y-%m-%d %H:%M"), "text": t}
                for b, t in blocks
            ]
        }, f)

def check_and_send():
    if not os.path.exists("schedule.json"):
        print("No schedule found.")
        return
    with open("schedule.json") as f:
        schedule = json.load(f)
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    remaining = []
    for entry in schedule["messages"]:
        if entry["time"] == now:
            send_telegram_message(entry["text"])
        else:
            remaining.append(entry)
    with open("schedule.json", "w") as f:
        json.dump({"messages": remaining}, f)

if __name__ == "__main__":
    mode = os.environ.get("MODE", "plan")  # "plan" or "run"
    if mode == "plan":
        prices = get_prices()
        blocks = []
        for label, start, end in [("morning", 6, 12), ("afternoon", 12, 18)]:
            block = find_cheapest_block(prices, start, end)
            if block:
                blocks.append((block, format_msg(label, block)))
        save_schedule(blocks)
    elif mode == "run":
        check_and_send()
