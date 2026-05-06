# Blinkit Hot Wheels Tracker Bot 🏎️🔥

A highly resilient, multi-location scraping bot built with **Python + Playwright**, designed to autonomously monitor [Blinkit](https://blinkit.com) for high-demand Hot Wheels drops and specific product restocks. Runs 24/7 in Docker (Render) or locally on Windows with full auto-restart. Delivers real-time **Telegram alerts** and **phone call notifications** via Twilio.

---

## 🌟 Core Features

### 1. Multi-Location Geolocation Spoofing
Blinkit inventory varies wildly by micro-location — a product available in South Delhi may not exist in North Delhi. The bot uses Playwright's geolocation spoofing to simulate browsers sitting in different areas simultaneously. Each location maintains its own independent tracking state, search history, and alert cooldowns.

### 2. General Drop Scanner
Continuously scans Blinkit's search page for a configurable query (default: `hot wheels`).
- Triggers multiple lazy-loads by programmatically scrolling the page
- Extracts and parses raw text from product cards (`div[role='button']`)
- Filters results using an optional strict `KEYWORDS` list
- Detects **new products** that weren't seen in previous loops
- Validates availability by checking for `ADD` buttons and filtering out `Out of Stock` / `Notify` items
- Sends a `🔥 DROP` alert with formatted details: Name, Price, Quantity, Delivery Time

### 3. Precision Sniper Module
For highly coveted items where search results aren't enough. Monitors an explicit list of `PRODUCT_URLS` — direct Blinkit product page links.
- Navigates directly to each product page, bypassing search cache
- **Text-based stock detection** — extracts the page body text and isolates the main product section by cutting off at "Top products in this category" / "People also bought" dividers. This prevents false positives from `ADD` buttons on similar product recommendations
- Checks the isolated main section for:
  - ✅ Presence of `ADD` button text → **In Stock**
  - ❌ Presence of `out of stock`, `notify`, `currently unavailable` → **Not Available**
- Sends a `🔥 PRODUCT LIVE` alert + **phone call** when a product comes into stock
- Maintains state: alerts once on restock, goes silent, and re-arms only if the product goes back out of stock

### 4. Phone Call Alerts (Twilio)
When a sniper link detects a product in stock, the bot **calls your phone** with a text-to-speech message (Indian English voice, repeated 3 times). This ensures you never miss a critical restock, even if you're away from your screen.
- Uses Twilio Voice API with `Polly.Aditi` TTS voice
- Gracefully degrades — if Twilio isn't configured, calls are skipped silently
- Message includes product name and location for immediate action

### 5. Data Saver Mode
Each browser context intercepts network requests and blocks:
- Images, media, and fonts (~80% bandwidth savings)
- Common trackers: Google Analytics, Doubleclick, Facebook, Hotjar, Mixpanel

---

## 🛡️ Self-Healing Architecture

Web scraping 24/7 is notoriously unstable. This bot implements multiple layers of resilience to ensure uptime without manual intervention.

### Fatal Browser Crash Auto-Recovery
If Chromium dies (OOM, segfault), Playwright throws `Target closed` / `Browser disconnected` exceptions. The bot detects these specific error strings and forces a process exit (`os._exit(1)`), allowing the container or local auto-restart wrapper to reboot with a clean browser.

### Watchdog Deadlock Detector
If the main Python thread freezes or deadlocks, the process stays "alive" silently — invisible to health checks. The bot solves this with a background HTTP server that checks `LAST_LOOP_TIME`. If the main loop hasn't run in `WATCHDOG_TIMEOUT` seconds (default: 300s), the HTTP server returns `500`, triggering Render's health check to restart the container.

### CAPTCHA & IP Block Evasion
Blinkit (via Cloudflare) may block the bot's IP. The bot parses the DOM every loop for block signatures (`verify you are human`, `access denied`, `just a moment`). If detected:
1. Sends a `🚨 CAPTCHA/IP BLOCK DETECTED` Telegram alert
2. Pauses for `BLOCK_PAUSE_MINUTES` (keeps watchdog alive during pause)
3. Restarts the process to attempt IP rotation

### Smart Page Load Retry (Local Mode)
When running without a proxy, page load failures trigger a **30-second retry** instead of an immediate process kill. This handles temporary network blips without crash-looping. With a proxy configured, failures trigger an immediate restart for IP rotation.

### Crash Notification
Unhandled exceptions are caught at the top level. Before the process dies, a `💀 BOT CRASHED` message is sent to Telegram with the error details, so you always know what happened.

### Scheduled Daily Purge
To prevent memory leaks from accumulating over weeks of continuous page reloads, the bot performs a scheduled restart at `RESTART_HOUR` (default: 9 PM IST).

### Dynamic Heartbeats
The bot pings Telegram at `HEARTBEAT_HOURS` (default: 9 AM and 9 PM) with a `✅ Bot is online` message for peace of mind.

---

## 🖥️ Local Deployment (Windows)

### Prerequisites
- Python 3.10+
- PowerShell 5.1+

### Setup
```powershell
# Clone the repo
git clone https://github.com/satyyam01/HW_Track_Bot.git
cd HW_Track_Bot

# Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure environment
cp .env.example .env   # Then edit .env with your values
```

### Running
```powershell
.\run_local.ps1
```

This launches **3 separate PowerShell windows**, one per city (Delhi1, Delhi2, Bangalore), each with:
- **Auto-restart on crash** — 10-second cooldown, then automatic relaunch
- **Crash-loop protection** — if the bot crashes 10+ times in 5 minutes, it backs off for 2 minutes
- **Log files** — saved to `logs/<BotName>.log` with timestamps
- **Window titles** — `HW Bot: Delhi1 (Auto-Restart)` for easy identification

### Console Output
```
========================================
  Bot: Delhi1  |  AUTO-RESTART: ON
  Location: Delhi1:28.6324096:77.3087659
========================================

[2026-05-06 21:07:57] --- Starting bot (run #1) ---
[21:07:58] 🚀 Starting watcher...
[21:08:01] [Delhi1] Loading Blinkit... (Timeout: 60000ms)
[21:08:05] [Delhi1] Clicked 'Detect my location'
[21:08:15] [Delhi1] Checked — 4 products, no new finds.
[21:08:15] [Delhi1] Checked 746598 | MainAdd: False | OOS: True | InStock: False
```

---

## ☁️ Cloud Deployment (Render / Docker)

### Dockerfile
Uses the official `mcr.microsoft.com/playwright/python:v1.40.0-jammy` image with all Chromium OS dependencies pre-installed.

```bash
# Build and run locally
docker build -t hw-tracker .
docker run --env-file .env hw-tracker
```

### Render Setup
1. Create a new **Web Service** on [Render](https://render.com)
2. Connect your GitHub repository
3. Set all environment variables from the table below
4. The dummy HTTP server on `$PORT` satisfies Render's health check requirement
5. Render automatically restarts the container on `os._exit(1)` calls

### Startup Flow
```
Bot starts → Parse locations → Verify env vars
  → Launch browser (headless Chromium)
  → For each location:
      → Open Blinkit search page
      → Dismiss app banner → Click "Detect my location"
  → Enter main monitoring loop
  → Send heartbeat on schedule
```

---

## ⚙️ Configuration (.env)

The bot is entirely driven by environment variables. No code changes required.

### Core Settings

| Variable | Description | Default |
|:---|:---|:---|
| `BOT_TOKEN` | Telegram Bot API token | *required* |
| `CHAT_ID` | Telegram Chat ID(s), comma-separated for multi-user | *required* |
| `LOCATIONS` | `Name:Lat:Lng` format, comma-separated | *required* |
| `TRACK_QUERY` | Search term for Blinkit | `hot wheels` |
| `KEYWORDS` | Only alert if product contains these words (comma-separated). Leave empty for all. | *(empty)* |
| `PRODUCT_URLS` | Direct Blinkit product URLs for sniper mode (comma-separated) | *(empty)* |

### Timing

| Variable | Description | Default |
|:---|:---|:---|
| `CHECK_INTERVAL` | Seconds between standard scan loops | `8` |
| `COOLDOWN` | Seconds to pause after a successful drop alert | `40` |
| `HEARTBEAT_HOURS` | Hours (0-23, IST) to send "online" pings | `9,21` |
| `RESTART_HOUR` | Hour (0-23, IST) for daily memory purge restart | `21` |
| `BLOCK_PAUSE_MINUTES` | Minutes to pause when CAPTCHA/IP block detected | `60` |

### Network & Performance

| Variable | Description | Default |
|:---|:---|:---|
| `PROXY_URL` | HTTP proxy URL (e.g. `http://user:pass@host:port`). Leave empty for direct. | *(empty)* |
| `PAGE_TIMEOUT` | Max milliseconds to wait for page load | `60000` |
| `WATCHDOG_TIMEOUT` | Seconds before watchdog considers main loop dead | `180` |

### Twilio Voice Calls (Optional)

| Variable | Description | Example |
|:---|:---|:---|
| `TWILIO_ACCOUNT_SID` | From [Twilio Console](https://console.twilio.com) | `ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `TWILIO_AUTH_TOKEN` | From Twilio Console | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `TWILIO_PHONE_NUMBER` | Your Twilio phone number | `+18165679803` |
| `MY_PHONE_NUMBER` | Your personal phone number to receive calls | `+919660966724` |

> **Note:** If any Twilio variable is missing, phone calls are silently skipped. The bot works fine without Twilio — you just won't get call alerts.

---

## 📱 Alert Types

| Event | Telegram | Phone Call | When |
|:---|:---:|:---:|:---|
| New product found in search | ✅ `🔥 DROP` | ❌ | Every scan loop |
| Sniper link comes IN STOCK | ✅ `🔥 PRODUCT LIVE` | ✅ 📞 | Once per restock cycle |
| CAPTCHA / IP block detected | ✅ `🚨 BLOCK` | ❌ | On detection |
| Bot crashes | ✅ `💀 CRASHED` | ❌ | On unhandled exception |
| Heartbeat | ✅ `✅ Online` | ❌ | At `HEARTBEAT_HOURS` |
| Scheduled restart | ✅ `♻️ Restarting` | ❌ | At `RESTART_HOUR` |

---

## 📁 Project Structure

```
HW_Track_Bot/
├── watcher.py              # Main bot — scanner, sniper, alerts, self-healing
├── run_local.ps1           # Windows launcher with auto-restart per city
├── Dockerfile              # Render/Docker deployment config
├── requirements.txt        # Python dependencies
├── .env                    # Environment configuration (gitignored)
├── .gitignore
├── README.md
└── logs/                   # Auto-restart crash logs (gitignored)
    ├── Delhi1.log
    ├── Delhi2.log
    └── Bangalore.log
```

---

## 🔧 Dependencies

| Package | Version | Purpose |
|:---|:---|:---|
| `playwright` | 1.40.0 | Headless Chromium browser automation |
| `python-dotenv` | 1.0.0 | Load `.env` configuration |
| `requests` | 2.31.0 | Telegram API calls |
| `twilio` | 9.4.0 | Phone call alerts (optional) |

---

## 📝 Changelog

### v2.1 — Auto-Restart & Phone Calls (May 2026)
- **Phone call alerts** via Twilio when sniper links detect stock
- **Auto-restart wrapper** for local deployment with crash-loop protection
- **Crash notifications** sent to Telegram before process dies
- **Fixed sniper false positives** — isolates main product section from "Similar Products" recommendations
- **Smart retry** on page load failures (local mode)

### v2.0 — Multi-Location & Sniper (Apr 2026)
- Multi-location geolocation spoofing
- Precision sniper module for direct product URLs
- Watchdog deadlock detector
- CAPTCHA/IP block detection
- Data saver mode (block images, fonts, trackers)
- Scheduled daily restarts and heartbeats

### v1.0 — Initial Release
- Basic Blinkit search scraping
- Telegram notifications
- Single location support
