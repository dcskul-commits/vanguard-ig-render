import os
import sys
import json
import time
import glob
from datetime import datetime, timedelta, time as dtime
import pytz
from instagrapi import Client

# Force instant unbuffered output so Render logs appear in real time
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 1. CONFIGURATION
# ==========================================
TIMEZONE = os.environ.get("TIMEZONE", "America/Denver")
IG_USERNAME = os.environ.get("IG_USERNAME", "the_david_skul")
IG_SESSION_ID = os.environ.get("IG_SESSION_ID", "")
PROXY_URL = os.environ.get("PROXY_URL", "")

# Disk location on Render (/data if Render Persistent Disk is attached, else local)
DATA_DIR = os.environ.get("DATA_DIR", "/data" if os.path.exists("/data") else ".")
IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "images")

SESSION_FILE = os.path.join(DATA_DIR, "ig_session.json")
HISTORY_FILE = os.path.join(DATA_DIR, "ig_posting_history.json")

# Posting Window: Monday-Saturday between 10:00 AM and 6:30 PM
WINDOW_START_HOUR = 10
WINDOW_START_MINUTE = 0
WINDOW_END_HOUR = 18
WINDOW_END_MINUTE = 30

CAPTION = (
    "Transform your biological baseline with clinical-grade peptide science. 🧬✨\n\n"
    "Targeted formulations designed to optimize cellular repair, longevity, and metabolic recovery.\n\n"
    "👉 Tap the link in bio or visit VanguardBIO.ai\n\n"
    "#VanguardBIO #Longevity #CellularRepair #Peptides #AntiAging #HealthOptimization"
)

# ==========================================
# 2. STATE PERSISTENCE
# ==========================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def mark_as_posted(filename, media_pk):
    history = load_history()
    tz = pytz.timezone(TIMEZONE)
    history[filename] = {
        "posted_at": datetime.now(tz).isoformat(),
        "media_pk": str(media_pk)
    }
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

# ==========================================
# 3. INSTAGRAM CLIENT INITIALIZATION
# ==========================================
def get_client():
    cl = Client()
    if PROXY_URL:
        cl.set_proxy(PROXY_URL)

    cl.set_device({
        "app_version": "340.0.0.35.106",
        "android_version": 34,
        "android_release": "14.0",
        "dpi": "480dpi",
        "resolution": "1080x2400",
        "manufacturer": "samsung",
        "device": "SM-S928B",
        "model": "eureka",
        "cpu": "qcom",
        "version_code": "620035106"
    })
    cl.set_user_agent(
        "Instagram 340.0.0.35.106 Android (34/14.0; 480dpi; 1080x2400; samsung; SM-S928B; eureka; qcom; en_US; 620035106)"
    )

    # Bypass deprecated Meta QE endpoints returning 404
    orig_private_request = cl.private_request
    def safe_private_request(endpoint, *args, **kwargs):
        if "qe/expose" in endpoint or "qe/sync" in endpoint:
            return {"status": "ok"}
        return orig_private_request(endpoint, *args, **kwargs)
    cl.private_request = safe_private_request

    if hasattr(cl, "expose"):
        cl.expose = lambda *args, **kwargs: True
    if hasattr(cl, "qe_expose"):
        cl.qe_expose = lambda *args, **kwargs: True

    if os.path.exists(SESSION_FILE):
        try:
            cl.load_settings(SESSION_FILE)
            cl.get_timeline_feed()
            return cl
        except Exception:
            print("[*] Saved session expired. Re-authenticating...")

    if not IG_SESSION_ID:
        raise ValueError("Missing IG_SESSION_ID environment variable.")

    cl.login_by_sessionid(IG_SESSION_ID)
    cl.dump_settings(SESSION_FILE)
    return cl

# ==========================================
# 4. 30-DAY MON-SAT TIMELINE GENERATOR
# ==========================================
def build_even_distribution_schedule(image_files, tz):
    now = datetime.now(tz)
    total_days = 30
    
    start_sec = (WINDOW_START_HOUR * 3600) + (WINDOW_START_MINUTE * 60)
    end_sec = (WINDOW_END_HOUR * 3600) + (WINDOW_END_MINUTE * 60)
    daily_active_seconds = end_sec - start_sec

    eligible_dates = []
    base_date = now.date()
    for d in range(total_days):
        day_date = base_date + timedelta(days=d)
        if day_date.weekday() != 6:  # Skip Sundays
            eligible_dates.append(day_date)

    total_active_seconds = len(eligible_dates) * daily_active_seconds
    num_images = len(image_files)
    
    if num_images == 0:
        return []

    interval = total_active_seconds / num_images
    schedule_plan = []

    for idx, img_path in enumerate(image_files):
        target_active_second = (idx + 0.5) * interval
        day_index = int(target_active_second // daily_active_seconds)
        if day_index >= len(eligible_dates):
            day_index = len(eligible_dates) - 1

        sec_into_day = int(target_active_second % daily_active_seconds)
        post_time_sec = start_sec + sec_into_day

        h = post_time_sec // 3600
        m = (post_time_sec % 3600) // 60
        s = post_time_sec % 60

        slot_datetime = tz.localize(datetime.combine(eligible_dates[day_index], dtime(h, m, s)))
        schedule_plan.append((slot_datetime, img_path))

    return schedule_plan

# ==========================================
# 5. MAIN SCHEDULER LOOP
# ==========================================
def run_scheduler():
    tz = pytz.timezone(TIMEZONE)
    print("=" * 60)
    print("VanguardBIO 30-Day Render Instagram Poster Initialized")
    print(f"Timezone: {TIMEZONE} | Window: 10:00 AM - 6:30 PM (Mon-Sat)")
    print(f"Data directory: {DATA_DIR}")
    print("=" * 60)

    # Diagnostic prints to inspect Render file structure
    print(f"DEBUG: Root contents: {os.listdir(os.path.dirname(__file__))}")
    if os.path.exists(IMAGE_FOLDER):
        print(f"DEBUG: 'images' folder contents: {os.listdir(IMAGE_FOLDER)}")
    else:
        print("DEBUG: 'images' folder does not exist at all on Render!")

    all_images = sorted(
        glob.glob(os.path.join(IMAGE_FOLDER, "*.png")) +
        glob.glob(os.path.join(IMAGE_FOLDER, "*.jpg")) +
        glob.glob(os.path.join(IMAGE_FOLDER, "*.jpeg"))
    )

    if not all_images:
        print(f"[-] No valid images found in '{IMAGE_FOLDER}'. Check file extensions (.png, .jpg).")
        while True:
            time.sleep(3600)

    print(f"[*] Found {len(all_images)} total images in repo.")
    
    schedule_plan = build_even_distribution_schedule(all_images, tz)
    for scheduled_time, img_path in schedule_plan:
        print(f"  -> {os.path.basename(img_path)} scheduled for: {scheduled_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    while True:
        now = datetime.now(tz)
        history = load_history()

        for scheduled_time, img_path in schedule_plan:
            filename = os.path.basename(img_path)
            
            if now >= scheduled_time and filename not in history:
                print(f"\n[*] Time reached for: {filename} ({scheduled_time.strftime('%Y-%m-%d %H:%M')})")
                try:
                    cl = get_client()
                    print(f"[*] Uploading {filename}...")
                    media = cl.photo_upload(img_path, CAPTION)
                    mark_as_posted(filename, media.pk)
                    print(f"[✓] Successfully published {filename} (Media ID: {media.pk})")
                except Exception as e:
                    print(f"[-] Error uploading {filename}: {e}")

        time.sleep(60)

if __name__ == "__main__":
    run_scheduler()
