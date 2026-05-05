# Blinkit Hot Wheels Tracker Bot 🏎️🔥

A highly resilient, multi-location scraping bot built with Python and Playwright, designed to autonomously monitor Blinkit for high-demand Hot Wheels drops and specific product restocks. The bot operates 24/7 in a Dockerized environment (e.g., Render) and delivers real-time Telegram alerts.

## 🌟 Core Features

### 1. Multi-Location Geolocation Spoofing
Blinkit inventory varies wildly by micro-location. The bot uses Playwright's advanced geolocation spoofing to simulate browsers simultaneously sitting in different areas (e.g., Bangalore, Delhi). Each location maintains its own independent tracking state.

### 2. General Drop Scanner
The bot continuously scans the Blinkit search page for a specific query (default: `hot wheels`). 
*   It triggers multiple lazy-loads by scrolling the page.
*   Extracts and parses the raw text from product cards.
*   Filters results using an optional strict list of `KEYWORDS`.
*   If it detects a product that wasn't seen in previous loops, it sends a `🔥 DROP` alert with formatted details (Name, Price, Quantity, Delivery Time).

### 3. Precision Sniper Module
For highly coveted items, search results aren't enough. The sniper module checks an explicit list of `PRODUCT_URLS`.
*   It bypasses cache and goes directly to the product page.
*   Validates stock by dynamically ensuring the presence of an `ADD` button while confirming the absence of `Out of stock` text.
*   Sends a specialized `🔥 PRODUCT LIVE` alert.
*   Maintains state: It alerts once when it comes into stock, goes silent, and arms itself again only if the product goes out of stock.

## 🛡️ Bulletproof Resilience Mechanisms

Web scraping 24/7 is notoriously unstable due to memory leaks, browser crashes, and IP bans. This bot implements an extensive **Self-Healing Architecture** to ensure 100% uptime without manual intervention.

*   **Fatal Browser Crash Auto-Recovery:** 
    If the underlying Chromium process dies (e.g., out of memory), Playwright throws `Target closed` exceptions. The script detects these specific errors and forces a process exit (`os._exit(1)`), allowing the Docker container/Render platform to reboot the bot with a clean browser.
*   **Watchdog Deadlock Detector:** 
    If the main Python thread completely freezes or deadlocks (a rare but fatal issue in async wrappers), the script would normally stay "alive" silently. We solved this by pairing the main loop with a background Dummy HTTP Server. The main loop updates a `LAST_LOOP_TIME` variable every few seconds. If the HTTP server notices the main loop hasn't run in 5 minutes, it intentionally returns a `500 Internal Server Error`. Render detects this failed health check and violently restarts the container.
*   **Proactive CAPTCHA & IP Block Evasion:** 
    Blinkit (via Cloudflare) may occasionally block the bot's IP. The bot constantly parses the DOM for block signatures like `verify you are human` or `access denied`. If detected, it instantly alerts the admin (`🚨 CAPTCHA/IP BLOCK DETECTED`) and restarts the container to attempt to cycle to a new IP address.
*   **Scheduled Daily Purge:** 
    To proactively prevent memory leaks from building up over weeks of continuous page reloads, the bot performs a scheduled daily restart at a configurable hour (`RESTART_HOUR`). 
*   **Dynamic Heartbeats:** 
    To give you peace of mind, the bot pings you on Telegram at specific times (`HEARTBEAT_HOURS`) verifying that it is "online and operational".

## ⚙️ Configuration (.env)

The bot is entirely driven by environment variables. No code changes are required to modify its behavior.

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `BOT_TOKEN` | Telegram Bot API Token | `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
| `CHAT_ID` | Telegram Chat ID(s) (comma separated) | `123456789,987654321` |
| `LOCATIONS` | Name:Lat:Lng format (comma separated) | `Bangalore:12.924:77.625,Delhi:28.63:77.30` |
| `TRACK_QUERY` | Term to type into Blinkit search | `hot wheels` |
| `KEYWORDS` | Only alert if these words are present | `assortment, 5 pack` (Leave empty to allow all) |
| `PRODUCT_URLS` | Specific Blinkit product links to snipe | `https://blinkit.com/prn/x/prid/746598,...` |
| `CHECK_INTERVAL` | Seconds to sleep between standard loops | `8` |
| `COOLDOWN` | Seconds to sleep after a successful drop alert | `40` |
| `HEARTBEAT_HOURS` | Hours (0-23) to send the "online" ping | `9,21` (9 AM and 9 PM IST) |
| `RESTART_HOUR` | Hour (0-23) to perform the daily purge restart | `21` (9 PM IST) |

## 🚀 Deployment (Render / Docker)

This bot is designed to be hosted on platforms like Render using the provided `Dockerfile`.

1.  **Dummy Web Server:** The bot runs a lightweight HTTP server on the port defined by `$PORT`. This is strictly to satisfy Render's web-service health checks, keeping the background bot alive.
2.  **Environment:** The Dockerfile utilizes the official `mcr.microsoft.com/playwright/python` image to ensure all Chromium OS dependencies are met out of the box.
3.  **Unbuffered Output:** Configured with `ENV PYTHONUNBUFFERED=1` to ensure logs flow immediately into the Render dashboard without delay.

### Startup Flow
When deployed, the bot will initialize, parse the locations, verify the environment variables, and send a `✅ HW Track Bot has started successfully` message to Telegram. From there, it requires zero maintenance.
