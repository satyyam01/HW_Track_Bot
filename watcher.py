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

HEARTBEAT_HOURS = [int(h.strip()) for h in os.getenv("HEARTBEAT_HOURS", "9,21").split(",") if h.strip().isdigit()]
try:
    RESTART_HOUR = int(os.getenv("RESTART_HOUR", "21").strip())
except ValueError:
    RESTART_HOUR = 21

try:
    BLOCK_PAUSE_MINUTES = int(os.getenv("BLOCK_PAUSE_MINUTES", "60").strip())
except ValueError:
    BLOCK_PAUSE_MINUTES = 60

try:
    PAGE_TIMEOUT = int(os.getenv("PAGE_TIMEOUT", "60000").strip())
except ValueError:
    PAGE_TIMEOUT = 60000

try:
    WATCHDOG_TIMEOUT = int(os.getenv("WATCHDOG_TIMEOUT", "300").strip())
except ValueError:
    WATCHDOG_TIMEOUT = 300

LAST_LOOP_TIME = time.time()

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
    chat_ids = [cid.strip() for cid in CHAT_ID.split(",") if cid.strip()]
    
    for chat_id in chat_ids:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": chat_id, "text": msg}
        try:
            res = requests.post(url, data=data, timeout=5)
            if res.status_code != 200:
                print(f"⚠️ Telegram Error (Chat {chat_id}): {res.text}")
        except Exception as e:
            print(f"⚠️ Telegram Exception (Chat {chat_id}): {e}")

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
    if PRODUCT_URLS:
        print(f"[{loc_name}] Starting sniper check for {len(PRODUCT_URLS)} links...")

    for url in PRODUCT_URLS:
        page = None
        try:
            page = context.new_page()
            page.goto(url, timeout=20000)
            page.wait_for_timeout(2500)
            
            current_url = page.url
            is_available = False
            
            # 1. Ensure we didn't get redirected to the homepage
            if "/prn/" in current_url or "/prid/" in current_url:
                
                # 2. Look for an exact "ADD" button
                buttons = page.locator("div[role='button'], button").all_inner_texts()
                has_add = any(b.strip().upper() in ["ADD", "ADD TO CART"] for b in buttons)
                
                # 3. Look for "Out of stock" text anywhere on the page
                oos_count = (
                    page.locator("text='Out of Stock'").count() + 
                    page.locator("text='Out of stock'").count() + 
                    page.locator("text='Currently Unavailable'").count()
                )
                
                # It's only truly available if an ADD button exists AND it doesn't say Out of Stock
                if has_add and oos_count == 0:
                    is_available = True
                    
            print(f"[{loc_name}] Checked link {url[-6:]} | In Stock: {is_available}")
            
            if is_available:
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
        proxy_cfg = None
        if os.getenv("PROXY_URL"):
            p_url = os.getenv("PROXY_URL")
            if "@" in p_url:
                # Parse http://user:pass@host:port
                import urllib.parse
                parsed = urllib.parse.urlparse(p_url)
                proxy_cfg = {
                    "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                    "username": parsed.username,
                    "password": parsed.password
                }
            else:
                proxy_cfg = {"server": p_url}
            print("🌐 Using Proxy Server configuration.")

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
            proxy=proxy_cfg
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
            try:
                page.goto(url, timeout=PAGE_TIMEOUT)
            except Exception as e:
                print(f"⚠️ Proxy Timeout on {loc['name']}. Rotating IP...")
                os._exit(1)

            # ---- Blinkit Specific Initialization ----
            try:
                page.wait_for_timeout(3000) # Wait for potential modals

                # 1. Dismiss "Continue on web" app banner if it exists
                app_banner = page.locator("text='Continue on web'")
                if app_banner.count() > 0:
                    app_banner.first.click()
                    page.wait_for_timeout(1000)

                # 2. Click "Detect my location" so the context's geolocation is actually used
                try:
                    loc_btn = page.locator("text='Detect my location'").first
                    loc_btn.wait_for(timeout=5000, state="visible")
                    loc_btn.click()
                    print(f"[{loc['name']}] Clicked 'Detect my location'")
                    page.wait_for_timeout(3000) # Wait for products to load
                except Exception:
                    print(f"[{loc['name']}] 'Detect my location' button not found or not visible.")
            except Exception as e:
                print(f"Setup error for {loc['name']}: {e}")
            # ----------------------------------------

            contexts[loc["name"]] = {
                "context": context,
                "page": page
            }
            seen_search_items[loc["name"]] = set()
            alerted_sniper_urls[loc["name"]] = set()

        from datetime import datetime, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        last_heartbeat_hour = datetime.now(IST).hour

        while True:
            from datetime import datetime, timezone, timedelta
            IST = timezone(timedelta(hours=5, minutes=30))
            now = datetime.now(IST)
            
            # Dynamic heartbeat check
            if now.hour in HEARTBEAT_HOURS and now.minute <= 5 and last_heartbeat_hour != now.hour:
                send_telegram(f"✅ HW Track Bot is online and operational. Monitoring {len(LOCATIONS)} locations.")
                last_heartbeat_hour = now.hour
                
                # Perform daily restart to clear memory and attempt IP rotation
                if now.hour == RESTART_HOUR:
                    send_telegram(f"♻️ HW Track Bot performing scheduled daily restart (Hour {RESTART_HOUR}) to clear memory...")
                    os._exit(1)

            triggered = False

            for name, ctx in contexts.items():
                global LAST_LOOP_TIME
                LAST_LOOP_TIME = time.time()

                page = ctx["page"]
                context = ctx["context"]

                try:
                    page.reload(timeout=PAGE_TIMEOUT)
                    page.wait_for_timeout(4000) # Wait for React to render product cards
                    # --- CAPTCHA / IP BLOCK CHECK ---
                    try:
                        page_text = page.locator("body").inner_text().lower()
                        if "verify you are human" in page_text or "just a moment" in page_text or "access denied" in page_text:
                            msg = f"🚨 CAPTCHA/IP BLOCK DETECTED on {name}! Render IP is blocked by Blinkit. Pausing bot for {BLOCK_PAUSE_MINUTES} minutes to prevent spam..."
                            print(msg)
                            send_telegram(msg)
                            # Sleep in small chunks to keep watchdog alive
                            for _ in range(BLOCK_PAUSE_MINUTES):
                                LAST_LOOP_TIME = time.time()
                                time.sleep(60)
                            os._exit(1)
                    except Exception:
                        pass
                    # --------------------------------
                    
                    # Scroll multiple times to trigger lazy-loaded products
                    for _ in range(4):
                        page.mouse.wheel(0, 1000)
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
                    err_str = str(e).lower()
                    if "target closed" in err_str or "browser closed" in err_str or "disconnected" in err_str or "timeout" in err_str:
                        print("⚠️ FATAL: Browser or proxy failure detected. Exiting process to trigger container restart...")
                        os._exit(1)

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
            
        def do_HEAD(self):
            # Watchdog check: if main loop hasn't run in X seconds, return 500
            if time.time() - LAST_LOOP_TIME > WATCHDOG_TIMEOUT:
                self.send_response(500)
                self.send_header('Content-type','text/plain')
                self.end_headers()
                return
                
            self.send_response(200)
            self.send_header('Content-type','text/plain')
            self.end_headers()
    
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"🌐 Started dummy web server on port {port} to satisfy Render requirements.")
    server.serve_forever()

if __name__ == "__main__":
    if os.environ.get("RENDER") or os.environ.get("PORT"):
        threading.Thread(target=start_dummy_server, daemon=True).start()
    run()
