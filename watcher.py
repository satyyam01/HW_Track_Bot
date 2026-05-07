import os
import time
import requests
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

QUERY = os.getenv("TRACK_QUERY", "hot wheels")

KEYWORDS = [k.strip().lower() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]
VIP_KEYWORDS = [k.strip().lower() for k in os.getenv("VIP_KEYWORDS", "").split(",") if k.strip()]
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
    WATCHDOG_TIMEOUT = int(os.getenv("WATCHDOG_TIMEOUT", "180").strip())
except ValueError:
    WATCHDOG_TIMEOUT = 180

# --- Twilio Voice Call Config ---
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE = os.getenv("TWILIO_PHONE_NUMBER", "")  # Your Twilio number (e.g. +1234567890)
MY_PHONE = os.getenv("MY_PHONE_NUMBER", "")            # Your personal number to call (e.g. +91XXXXXXXXXX)
CALL_ENABLED = all([TWILIO_SID, TWILIO_AUTH, TWILIO_PHONE, MY_PHONE, TWILIO_AVAILABLE])

LAST_LOOP_TIME = time.time()

IST = timezone(timedelta(hours=5, minutes=30))

def log(msg):
    """Print with IST timestamp prefix."""
    ts = datetime.now(IST).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

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
                log(f"⚠️ Telegram Error (Chat {chat_id}): {res.text}")
        except Exception as e:
            log(f"⚠️ Telegram Exception (Chat {chat_id}): {e}")

def make_call(product_info, loc_name):
    """Make a phone call via Twilio to alert about sniper product in stock."""
    if not CALL_ENABLED:
        log("📞 Call skipped — Twilio not configured.")
        return

    try:
        client = TwilioClient(TWILIO_SID, TWILIO_AUTH)

        # TwiML for text-to-speech message, repeated 3 times so you don't miss it
        twiml = (
            '<Response>'
            '<Say voice="Polly.Aditi" language="en-IN" loop="3">'
            f'Alert! Your Hot Wheels sniper link is now in stock in {loc_name}. '
            f'{product_info}. '
            'Open Blinkit immediately and place your order! '
            '</Say>'
            '</Response>'
        )

        call = client.calls.create(
            to=MY_PHONE,
            from_=TWILIO_PHONE,
            twiml=twiml,
            timeout=30
        )

        log(f"📞 Phone call initiated! SID: {call.sid}")
    except Exception as e:
        log(f"⚠️ Phone call failed: {e}")

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
    formatted = f"🏎️ {name}\n💰 {price}{qty_str} | ⏱️ {time_est}"
    return (name, formatted)  # Return tuple: (name for dedup, full string for display)

def extract_products(page):
    items = []

    try:
        # Blinkit product cards are divs with role="button"], not <a> tags!
        cards = page.locator("div[role='button']").all()

        for card in cards:
            try:
                text = card.inner_text()
                text_lower = text.lower().replace("₹", "rs. ")

                if "hot wheels" not in text_lower or not matches_keywords(text_lower):
                    continue
                if "\n" not in text_lower and "rs." not in text_lower:
                    continue

                # --- AVAILABILITY CHECK (same as sniper) ---
                # Check for "ADD" button inside this specific card
                card_buttons = card.locator("div[role='button'], button").all_inner_texts()
                has_add = any(b.strip().upper() in ["ADD", "ADD TO CART"] for b in card_buttons)

                # Check for out-of-stock / notify indicators
                has_oos = any(x in text_lower for x in ["out of stock", "currently unavailable", "notify me", "notify", "coming soon"])

                if not has_add and not has_oos:
                    # If no ADD button but also no OOS text, still include it
                    # (some cards have price but ADD button is in a nested element)
                    has_add = "rs." in text_lower or "₹" in text.lower()

                if has_oos:
                    continue  # Skip out-of-stock products

                name, formatted = format_product_text(text.replace("₹", "Rs. "))
                items.append((name, formatted))
            except:
                continue

    except:
        pass

    return list(set(items))

def _sniper_stock_check(page, loc_name, url_suffix):
    """
    Single stock check for a sniper product page.
    Returns (has_add, has_oos, is_available).
    Assumes the page is already loaded and hydrated.
    """
    current_url = page.url

    if "/prn/" not in current_url and "/prid/" not in current_url:
        log(f"[{loc_name}] Checked link {url_suffix} | Redirected to homepage, skipping")
        return (False, False, False)

    body_text = ""
    try:
        body_text = page.locator("body").inner_text()
    except Exception:
        return (False, False, False)

    # Isolate main product section — cut off recommendation widgets
    main_text = body_text.lower()
    divider_found = False
    for divider in ["top products in this category", "people also bought",
                     "similar products", "you might also like",
                     "explore more from this category", "frequently bought together"]:
        idx = main_text.find(divider)
        if idx != -1:
            main_text = main_text[:idx]
            divider_found = True
            break

    if not divider_found:
        # No divider found — the entire page text is being searched.
        # This is risky: recommendation ADD buttons could leak in.
        log(f"[{loc_name}] ⚠️ {url_suffix} — no section divider found, full-page text used (higher FP risk)")

    # Check for OOS / Notify indicators
    has_oos = any(x in main_text for x in [
        "out of stock", "currently unavailable", "notify me",
        "notify when available", "notify", "coming soon", "sold out"
    ])

    # Check for ADD button text
    has_add = "\nadd\n" in main_text or main_text.strip().endswith("\nadd")

    is_available = has_add and not has_oos
    return (has_add, has_oos, is_available)


def check_product_pages(context, loc_name, alerted_urls):
    triggered = False
    if PRODUCT_URLS:
        log(f"[{loc_name}] Starting sniper check for {len(PRODUCT_URLS)} links...")

    for url in PRODUCT_URLS:
        page = None
        try:
            page = context.new_page()
            page.goto(url, timeout=20000)
            page.wait_for_timeout(4000)  # Increased from 2500ms for React hydration

            url_suffix = url[-6:]
            has_add, has_oos, is_available = _sniper_stock_check(page, loc_name, url_suffix)
            log(f"[{loc_name}] Checked {url_suffix} | MainAdd: {has_add} | OOS: {has_oos} | InStock: {is_available}")

            # --- CONFIRMATION RE-CHECK ---
            # If stock detected, reload and verify to eliminate false positives
            # from hydration races, CDN caching, or stale DOM state.
            if is_available:
                log(f"[{loc_name}] ⚡ Stock detected for {url_suffix} — confirming with re-check...")
                page.reload(timeout=20000)
                page.wait_for_timeout(4000)

                has_add2, has_oos2, confirmed = _sniper_stock_check(page, loc_name, url_suffix)
                log(f"[{loc_name}] Re-check {url_suffix} | MainAdd: {has_add2} | OOS: {has_oos2} | Confirmed: {confirmed}")

                if not confirmed:
                    log(f"[{loc_name}] ❌ FALSE POSITIVE caught for {url_suffix} — not confirmed on re-check")
                    is_available = False

            if is_available:
                if url not in alerted_urls:
                    send_telegram(f"🔥 PRODUCT LIVE ({loc_name})\n{url}")
                    # Extract product name from URL for the call
                    url_product = url.split("/prn/")[-1].split("/")[0].replace("-", " ") if "/prn/" in url else "sniper target"
                    make_call(url_product, loc_name)
                    alerted_urls.add(url)
                    triggered = True
            else:
                # Reset if it goes out of stock
                if url in alerted_urls:
                    alerted_urls.remove(url)

        except Exception as e:
            log(f"[{loc_name}] Sniper check error for {url[-6:]}: {e}")
        finally:
            if page:
                try:
                    page.close()
                except:
                    pass

    return triggered

def run():
    log("🚀 Starting watcher...")

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
            log("🌐 Using Proxy Server configuration.")

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

            # --- DATA SAVER MODE ---
            # Blocks images, media, fonts, and common analytics to save ~80% bandwidth
            def handle_route(route):
                if route.request.resource_type in ["image", "media", "font"]:
                    return route.abort()
                # Block common trackers/analytics
                url = route.request.url.lower()
                if any(x in url for x in ["google-analytics", "doubleclick", "facebook", "analytics", "hotjar", "mixpanel"]):
                    return route.abort()
                return route.continue_()

            context.route("**/*", handle_route)

            page = context.new_page()
            url = f"https://blinkit.com/s/?q={QUERY.replace(' ', '%20')}"
            log(f"[{loc['name']}] Loading Blinkit... (Timeout: {PAGE_TIMEOUT}ms)")
            time.sleep(2) # Stagger to avoid proxy spikes
            try:
                page.goto(url, timeout=PAGE_TIMEOUT)
            except Exception as e:
                if os.getenv("PROXY_URL"):
                    log(f"⚠️ Proxy error on {loc['name']}: {e}. Rotating IP...")
                    os._exit(1)
                else:
                    log(f"⚠️ Page load failed on {loc['name']}: {e}. Retrying in 30s...")
                    time.sleep(30)
                    try:
                        page.goto(url, timeout=PAGE_TIMEOUT)
                    except Exception as e2:
                        log(f"❌ Page load failed again on {loc['name']}: {e2}. Restarting...")
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
                    log(f"[{loc['name']}] Clicked 'Detect my location'")
                    page.wait_for_timeout(3000) # Wait for products to load
                except Exception:
                    log(f"[{loc['name']}] 'Detect my location' button not found or not visible.")
            except Exception as e:
                log(f"Setup error for {loc['name']}: {e}")
            # ----------------------------------------

            contexts[loc["name"]] = {
                "context": context,
                "page": page
            }
            seen_search_items[loc["name"]] = set()
            alerted_sniper_urls[loc["name"]] = set()

        last_heartbeat_hour = datetime.now(IST).hour

        while True:
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
                            log(msg)
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
                    
                    potential_new_hits = []
                    for p_name, p_display in items:
                        if p_name not in seen_search_items[name]:
                            potential_new_hits.append((p_name, p_display))
                    
                    final_new_hits = []
                    vip_confirmed_count = 0
                    
                    # If any new items are found, RELOAD once to confirm they are real
                    if potential_new_hits:
                        log(f"[{name}] 🔍 {len(potential_new_hits)} potential new items found. Reloading to verify...")
                        page.reload(timeout=PAGE_TIMEOUT)
                        page.wait_for_timeout(5000)
                        
                        confirmed_items = extract_products(page)
                        confirmed_names = {p[0] for p in confirmed_items}
                        
                        for p_name, p_display in potential_new_hits:
                            if p_name in confirmed_names:
                                seen_search_items[name].add(p_name)
                                final_new_hits.append(p_display)
                                
                                # Check if this confirmed item is a VIP
                                if any(vk in p_name.lower() for vk in VIP_KEYWORDS):
                                    vip_confirmed_count += 1
                                    log(f"[{name}] ✅ VIP Confirmed: {p_name}")
                                else:
                                    log(f"[{name}] ✅ Confirmed: {p_name}")
                            else:
                                log(f"[{name}] ❌ False Positive caught (disappeared after reload): {p_name}")

                    if final_new_hits:
                        log(f"[{name}] 🆕 Verified {len(final_new_hits)} NEW products!")
                        msg = f"🔥 DROP ({name})\n\n" + "\n\n".join(final_new_hits[:10])
                        log(f"\n{msg}\n")
                        send_telegram(msg)
                        
                        if vip_confirmed_count > 0:
                            make_call(f"Confirmed {vip_confirmed_count} high priority items", name)
                        
                        triggered = True
                    else:
                        if potential_new_hits:
                            log(f"[{name}] All {len(potential_new_hits)} potential hits were false positives.")
                        else:
                            log(f"[{name}] Checked — {len(items)} products, no new finds.")

                    # sniper check
                    if check_product_pages(context, name, alerted_sniper_urls[name]):
                        triggered = True

                except Exception as e:
                    log(f"Error ({name}): {e}")
                    err_str = str(e).lower()
                    if any(x in err_str for x in ["target closed", "browser closed", "disconnected", "timeout", "tunnel", "connection refused", "connection reset"]):
                        log("⚠️ FATAL: Browser or proxy failure detected. Exiting process to trigger container restart...")
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
    log(f"🌐 Started dummy web server on port {port} to satisfy Render requirements.")
    server.serve_forever()

if __name__ == "__main__":
    if os.environ.get("RENDER") or os.environ.get("PORT"):
        threading.Thread(target=start_dummy_server, daemon=True).start()

    try:
        run()
    except SystemExit:
        raise  # Let os._exit() and sys.exit() pass through
    except Exception as e:
        loc_names = ", ".join(l["name"] for l in LOCATIONS) if LOCATIONS else "unknown"
        crash_msg = f"💀 BOT CRASHED ({loc_names})\n\nError: {type(e).__name__}: {e}\n\n♻️ Auto-restart will recover in ~10 seconds..."
        log(f"FATAL UNHANDLED EXCEPTION: {e}")
        try:
            send_telegram(crash_msg)
        except Exception:
            pass  # Don't let Telegram failure prevent the exit
        import sys
        sys.exit(1)
