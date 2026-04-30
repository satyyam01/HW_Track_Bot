# Hot Wheels Track Bot (Blinkit Sniper) 🏎️💨

A robust, location-aware automated web scraper built with Python and Playwright. This bot continuously monitors Blinkit for incoming "Hot Wheels" restocks in specified geolocations, bypassing anti-bot measures and instantly alerting you via Telegram when drops occur.

## Features
- **Multi-Location Geofencing:** Monitor different city hubs (e.g., Delhi, Bangalore) simultaneously using isolated browser contexts.
- **Stealth Automation:** Uses specific browser arguments and User-Agent spoofing to bypass modern web anti-bot detection.
- **Clean Telegram Alerts:** Extracts raw DOM text and runs it through a custom parser to send beautiful, readable, emoji-rich inventory alerts directly to your phone.
- **Cloud Ready:** Includes Docker configurations and a lightweight threaded background server to natively support free-tier hosting on platforms like Render.

## Setup Instructions (Local)

1. **Install Dependencies:**
   Ensure you have Python 3.10+ installed, then run:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Environment Variables:**
   Create a `.env` file in the root directory and configure the following:
   ```env
   BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
   CHAT_ID="YOUR_PERSONAL_CHAT_ID"
   
   # Format: Name:Lat:Lng,Name:Lat:Lng
   LOCATIONS=Bangalore:12.9241054:77.6254245,Delhi:28.6324096:77.3087659
   
   TRACK_QUERY=hot wheels
   KEYWORDS=ferrari,porsche,civic,mustang,hot wheels
   
   # Optional
   CHECK_INTERVAL=10
   COOLDOWN=40
   ```

3. **Run the Sniper:**
   ```bash
   python watcher.py
   ```

## Cloud Hosting (Render)

This bot is specifically tailored to run on [Render's Free Web Service Tier](https://render.com/).

1. **Deploy using Docker:** Push this repository to GitHub (excluding the `.env` file). When creating a Web Service on Render, ensure you select **Docker** as your runtime language, not Python.
2. **Environment Secrets:** Input all your variables from the `.env` file into Render's Environment settings.
3. **Keep-Alive:** Render's free tier sleeps after 15 minutes of inactivity. The bot automatically spins up a dummy web server on port `8080` (or `$PORT`). To keep the script scraping 24/7, use a free service like [UptimeRobot](https://uptimerobot.com/) to ping your Render URL every 10 minutes.

## Disclaimer
This project is intended for educational purposes only. Automated scraping of commercial platforms should be done responsibly and in accordance with the target website's Terms of Service.
