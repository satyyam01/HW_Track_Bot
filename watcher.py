import os
import time
import requests
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

QUERY = os.getenv("TRACK_QUERY", "hot wheels")

KEYWORDS = [k.strip().lower() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
PRODUCT_URLS = [u.strip() for u in os.getenv("PRODUCT_URLS", "").split(",") if u.strip()]

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 8))
COOLDOWN = int(os.getenv("COOLDOWN", 40))

def parse_locations():
    raw = os.getenv("LOCATIONS", "")
    if not raw.strip():
        return []
    locations = []
    for item in raw.split(","):
        try:
            name, lat, lng = item.split(":")
            locations.append({
                "name": name,
                "lat": float(lat),
                "lng": float(lng)
            })
        except ValueError:
            pass
    return locations

LOCATIONS = parse_locations()

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        res = requests.post(url, data=data, timeout=5)
        if res.status_code != 200:
            print(f"⚠️ Telegram Error: {res.text}")
    except Exception as e:
        print(f"⚠️ Telegram Exception: {e}")

def matches_keywords(text):
    if not KEYWORDS:
        return True
    return any(k in text for k in KEYWORDS)

def format_product_text(raw_text):
    lines = [line.strip() for line in raw_text.split('\n') if line.strip() and line.strip().lower() != 'add']
    name = "Unknown Product"
    price = ""
    time_est = ""
    qty = ""
    
    for line in lines:
        l = line.lower()
        if "min" in l and any(c.isdigit() for c in l):
            time_est = line
        elif "rs." in l or "₹" in l:
            if not price:
                price = line.title()
        elif "% off" in l:
            pass
        elif l in ["1 pc", "1 unit", "1 set"] or (any(c.isdigit() for c in l) and ("pc" in l or "unit" in l or "set" in l)):
            qty = line
        else:
            if name == "Unknown Product" and len(line) > 3 and l != "dreamland publications":
                name = line.title()
                
    qty_str = f" ({qty})" if qty else ""
    return f"🏎️ {name}\n💰 {price}{qty_str} | ⏱️ {time_est}"

def extract_products(page):
    items = []

    try:
        # Blinkit product cards are divs with role="button", not <a> tags!
        texts = page.locator("div[role='button']").all_inner_texts()

        for text in texts:
            text_lower = text.lower().replace("₹", "rs. ")
            if "hot wheels" in text_lower and matches_keywords(text_lower):
                if "\n" in text_lower or "rs." in text_lower:
                    formatted = format_product_text(text.replace("₹", "Rs. "))
                    items.append(formatted)

    except:
        pass

    return list(set(items))

def check_product_pages(context, loc_name, alerted_urls):
    triggered = False

    for url in PRODUCT_URLS:
        page = None
        try:
            page = context.new_page()
            page.goto(url, timeout=15000)

            html = page.content().lower()

            if "add to cart" in html or "add" in html:
                if url not in alerted_urls:
                    send_telegram(f"🔥 PRODUCT LIVE ({loc_name})\n{url}")
                    alerted_urls.add(url)
                    triggered = True
            else:
                # Reset if it goes out of stock
                if url in alerted_urls:
                    alerted_urls.remove(url)

        except:
            pass
        finally:
            if page:
                try:
                    page.close()
                except:
                    pass

    return triggered

def run():
    print("🚀 Starting watcher...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        contexts = {}
        seen_search_items = {}
        alerted_sniper_urls = {}

        for loc in LOCATIONS:
            context = browser.new_context(
                geolocation={
                    "latitude": loc["lat"],
                    "longitude": loc["lng"]
                },
                permissions=["geolocation"],
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            page = context.new_page()
            url = f"https://blinkit.com/s/?q={QUERY.replace(' ', '%20')}"
            page.goto(url)

            # ---- Blinkit Specific Initialization ----
            try:
                page.wait_for_timeout(3000) # Wait for potential modals

                # 1. Dismiss "Continue on web" app banner if it exists
                app_banner = page.locator("text='Continue on web'")
                if app_banner.count() > 0:
                    app_banner.first.click()
                    page.wait_for_timeout(1000)

                # 2. Click "Detect my location" so the context's geolocation is actually used
                loc_btn = page.locator("text='Detect my location'")
                if loc_btn.count() > 0:
                    loc_btn.first.click()
                    page.wait_for_timeout(3000) # Wait for products to load
            except Exception as e:
                print(f"Setup error for {loc['name']}: {e}")
            # ----------------------------------------

            contexts[loc["name"]] = {
                "context": context,
                "page": page
            }
            seen_search_items[loc["name"]] = set()
            alerted_sniper_urls[loc["name"]] = set()

        while True:
            triggered = False

            for name, ctx in contexts.items():
                page = ctx["page"]
                context = ctx["context"]

                try:
                    page.reload(timeout=15000)
                    page.wait_for_timeout(4000) # Wait for React to render product cards
                    
                    page.mouse.wheel(0, 500)
                    page.wait_for_timeout(1000)

                    items = extract_products(page)
                    print(f"[{name}] Extracted {len(items)} matching products from search.")

                    new_hits = []

                    for item in items:
                        if item not in seen_search_items[name]:
                            seen_search_items[name].add(item)
                            new_hits.append(item)

                    if new_hits:
                        msg = f"🔥 DROP ({name})\n\n" + "\n\n".join(new_hits[:10])
                        print(f"\n{msg}\n") # Print to console
                        send_telegram(msg)
                        triggered = True

                    # sniper check
                    if check_product_pages(context, name, alerted_sniper_urls[name]):
                        triggered = True

                except Exception as e:
                    print(f"Error ({name}):", e)

            if triggered:
                time.sleep(COOLDOWN)
            else:
                time.sleep(CHECK_INTERVAL)

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type','text/plain')
            self.end_headers()
            self.wfile.write(b"Bot is running!")
    
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"🌐 Started dummy web server on port {port} to satisfy Render requirements.")
    server.serve_forever()

if __name__ == "__main__":
    if os.environ.get("RENDER") or os.environ.get("PORT"):
        threading.Thread(target=start_dummy_server, daemon=True).start()
    run()