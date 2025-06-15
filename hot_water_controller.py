import os
import json
import requests
from datetime import datetime, timedelta
import pytz

# Telegram config from env
BOT_TOKEN = os.environ["HOT_SWITCH_BOT_TOKEN"]
CHANNEL_ID = os.environ["AUTOMATIONS_CHANNEL_ID"]

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
    if len(window) < 3:
        return None
    best = min((window[i:i+3] for i in range(len(window)-2)),
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
    else:
        print(f"✅ Message sent: {msg[:50]}...")

def save_schedule(blocks):
    schedule_data = {
        "periods": []
    }
    
    for block, text in blocks:
        # Store both start and end times for each cheap period
        start_time = block[0]["start"]
        end_time = block[-1]["end"]
        
        schedule_data["periods"].append({
            "start_time": start_time.strftime("%Y-%m-%d %H:%M"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M"),
            "text": text,
            "notified": False  # Track if we've sent the "period started" message
        })
    
    with open("schedule.json", "w") as f:
        json.dump(schedule_data, f, indent=2)
    print(f"📅 Schedule saved with {len(blocks)} periods")

def check_and_send():
    if not os.path.exists("schedule.json"):
        print("❌ No schedule.json found.")
        return
    
    with open("schedule.json") as f:
        schedule = json.load(f)
    
    # Handle old format (messages) vs new format (periods)
    if "messages" in schedule and "periods" not in schedule:
        print("🔄 Converting old schedule format...")
        # Convert old format - assume 1.5 hour periods
        periods = []
        for msg in schedule["messages"]:
            start_dt = datetime.strptime(msg["time"], "%Y-%m-%d %H:%M")
            end_dt = start_dt + timedelta(hours=1, minutes=30)  # Assume 1.5 hour periods
            periods.append({
                "start_time": msg["time"],
                "end_time": end_dt.strftime("%Y-%m-%d %H:%M"),
                "text": msg["text"],
                "notified": False
            })
        schedule = {"periods": periods}
        # Save the converted format
        with open("schedule.json", "w") as f:
            json.dump(schedule, f, indent=2)
    
    now = datetime.now(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    print(f"🕐 Current time: {now_str}")
    
    updated = False
    in_cheap_period = False
    
    for period in schedule["periods"]:
        start_time = datetime.strptime(period["start_time"], "%Y-%m-%d %H:%M")
        end_time = datetime.strptime(period["end_time"], "%Y-%m-%d %H:%M")
        
        # Localize the times to the timezone
        start_time = tz.localize(start_time)
        end_time = tz.localize(end_time)
        
        # Check if current time is within this cheap period
        if start_time <= now < end_time:
            in_cheap_period = True
            print(f"🎯 Currently in cheap period: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}")
            
            # Send notification if we haven't already
            if not period.get("notified", False):
                send_telegram_message(f"🚨 CHEAP PERIOD ACTIVE NOW!\n\n{period['text']}")
                period["notified"] = True
                updated = True
            else:
                print("✅ Already notified about this period")
            break
    
    if not in_cheap_period:
        print("⏳ Not currently in a cheap period")
    
    # Save any updates
    if updated:
        with open("schedule.json", "w") as f:
            json.dump(schedule, f, indent=2)
        print("💾 Schedule updated")

if __name__ == "__main__":
    mode = os.environ.get("MODE", "plan")
    print(f"🚀 Running in {mode} mode")
    
    if mode == "plan":
        try:
            prices = get_prices()
            print(f"📊 Got {len(prices)} price periods")
            blocks = []
            for label, start, end in [("morning", 1, 7), ("afternoon", 8, 19)]:
                block = find_cheapest_block(prices, start, end)
                if block:
                    blocks.append((block, format_msg(label, block)))
                    print(f"✅ Found {label} block: {block[0]['start'].strftime('%H:%M')}-{block[-1]['end'].strftime('%H:%M')}")
                else:
                    print(f"❌ No {label} block found")
            save_schedule(blocks)
        except Exception as e:
            print(f"❌ Error in plan mode: {e}")
            raise
    elif mode == "run":
        try:
            check_and_send()
        except Exception as e:
            print(f"❌ Error in run mode: {e}")
            raise
