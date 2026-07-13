from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
import time
import json
import re
import os
import random
from urllib.parse import quote
import tempfile
import shutil

germany_states = [
    "baden-wuerttemberg"
    # "baden-baden"
]

OUTPUT_FILE = "baden_result.json"
PROGRESS_FILE = "progress.json"

MAX_PAGE_RETRIES = 3
RETRY_DELAY_SECONDS = 5
PAGE_DELAY_MIN_SECONDS = 2
PAGE_DELAY_MAX_SECONDS = 5
CLOUDFLARE_MANUAL_WAIT_SECONDS = 600
CHALLENGE_CLEAR_REFRESH_DELAY_SECONDS = 5
RESULT_WAIT_ATTEMPTS = 12
RESULT_WAIT_SECONDS = 2
RESULT_SELECTOR = "div.result-list-entry__container--main"

CHALLENGE_MARKERS = (
    "challenge-error-text",
    "_cf_chl_opt",
    "cdn-cgi/challenge-platform",
    "Enable JavaScript and cookies to continue",
    "Just a moment",
    "Verifying you are human",
    "cf-turnstile",
    "turnstile",
)
NETWORK_ERROR_MARKERS = (
    "ERR_NETWORK_CHANGED",
    "Your connection was interrupted",
    "A network change was detected",
)

# If the network error pattern repeats this many times, recreate the driver
NETWORK_ERROR_RESTART_THRESHOLD = 3
# Restart only after repeated errors to reduce browser/driver churn
NETWORK_ERROR_IMMEDIATE_RESTART = False
DRIVER_START_ATTEMPTS = 3
DRIVER_START_RETRY_SECONDS = 5

def init_driver():
    """Create a Chrome driver with hardened options and retry on startup failure."""
    global current_profile_dir

    try:
        current_profile_dir = tempfile.mkdtemp(prefix="scraper_profile_")
    except Exception:
        current_profile_dir = None

    for attempt in range(1, DRIVER_START_ATTEMPTS + 1):
        options = webdriver.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--no-first-run")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-features=NetworkService,NetworkServiceInProcess")
        if current_profile_dir:
            options.add_argument(f"--user-data-dir={current_profile_dir}")

        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        print(f"Starting Chrome with profile: {current_profile_dir} (attempt {attempt}/{DRIVER_START_ATTEMPTS})")
        try:
            return webdriver.Chrome(options=options)
        except WebDriverException as exc:
            print(f"Driver startup attempt {attempt} failed: {exc}")
            if attempt < DRIVER_START_ATTEMPTS:
                time.sleep(DRIVER_START_RETRY_SECONDS)
                continue
            raise

    raise RuntimeError("Unable to start Chrome driver")

def restart_driver():
    global driver
    print("Recreating Chrome driver to clear cache and prevent connection issues...")
    try:
        if driver is not None:
            driver.quit()
    except Exception as e:
        print(f"Error quitting driver: {e}")
    time.sleep(2)

    driver = init_driver()

driver = init_driver()

def clean_text(text):
    return re.sub(r"\s+", " ", text).strip()

def random_delay():
    time.sleep(random.uniform(PAGE_DELAY_MIN_SECONDS, PAGE_DELAY_MAX_SECONDS))

def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default
    return default

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def is_challenge_page(driver):
    try:
        page_source = driver.page_source
        if any(marker in page_source for marker in CHALLENGE_MARKERS):
            return True
        return bool(driver.find_elements(
            By.CSS_SELECTOR,
            "iframe[src*='challenges.cloudflare.com'], input[name='cf-turnstile-response']"
        ))
    except:
        return False

def is_network_error_page(driver):
    try:
        page_source = driver.page_source
        return any(marker in page_source for marker in NETWORK_ERROR_MARKERS)
    except:
        return False

def wait_for_result_containers(driver):
    """
    Polls for result containers. Handles:
    - Network errors: auto-refreshes immediately
    - Cloudflare challenge: waits up to 10 min for manual solve, then refreshes once
    """
    challenge_notice_shown = False
    network_notice_shown = False
    network_error_count = 0
    normal_wait_until = time.time() + (RESULT_WAIT_ATTEMPTS * RESULT_WAIT_SECONDS)
    challenge_wait_until = None
    challenge_clear_seen_at = None
    refreshed_after_challenge = False

    while time.time() < normal_wait_until or (
        challenge_wait_until is not None and time.time() < challenge_wait_until
    ):
        main_containers = driver.find_elements(By.CSS_SELECTOR, RESULT_SELECTOR)
        if main_containers:
            return main_containers

        challenge_active = is_challenge_page(driver)
        if challenge_active:
            challenge_clear_seen_at = None
            if not challenge_notice_shown:
                print("Cloudflare challenge detected. You have up to 10 minutes to solve it in Chrome.")
                challenge_notice_shown = True
                challenge_wait_until = time.time() + CLOUDFLARE_MANUAL_WAIT_SECONDS
        elif challenge_notice_shown and not refreshed_after_challenge:
            if challenge_clear_seen_at is None:
                challenge_clear_seen_at = time.time()
            elif time.time() - challenge_clear_seen_at >= CHALLENGE_CLEAR_REFRESH_DELAY_SECONDS:
                print("Cloudflare challenge cleared. Refreshing once to load results...")
                driver.refresh()
                random_delay()
                refreshed_after_challenge = True
                normal_wait_until = time.time() + (RESULT_WAIT_ATTEMPTS * RESULT_WAIT_SECONDS)

        if is_network_error_page(driver):
            network_error_count += 1
            if not network_notice_shown:
                print("Network error detected. Auto-refreshing...")
                network_notice_shown = True
            # Try a refresh first
            try:
                driver.refresh()
            except:
                pass
            # Try clearing browser cache and cookies via CDP before restarting
            try:
                driver.execute_cdp_cmd("Network.clearBrowserCache", {})
                driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
            except Exception:
                pass
            # If repeated network errors, restart the driver to clear state
            if NETWORK_ERROR_IMMEDIATE_RESTART or network_error_count >= NETWORK_ERROR_RESTART_THRESHOLD:
                print(f"Network error persisted {network_error_count} times — restarting driver...")
                try:
                    restart_driver()
                except Exception:
                    pass
                network_error_count = 0

        time.sleep(RESULT_WAIT_SECONDS)

    return driver.find_elements(By.CSS_SELECTOR, RESULT_SELECTOR)

def load_page_with_retries(state, page):
    """Load the page and retry up to MAX_PAGE_RETRIES times on network/cloudflare failures."""
    url = (
        f"https://www.11880.com/suche/-/{quote(state.lower(), safe='-')}"
        f"?personen=1"
        f"&eigenschaften=telefon%7Cmobil"
        f"&sorte=%7C"
        f"&modul=direct"
        f"&page={page}"
    )

    for attempt in range(1, MAX_PAGE_RETRIES + 1):
        print(f"State: {state} | Page: {page} | Attempt: {attempt}")
        try:
            driver.get(url)
            random_delay()

            main_containers = wait_for_result_containers(driver)
            if main_containers:
                return main_containers

            if is_challenge_page(driver):
                print("Challenge still active after waiting. Retrying same page...")
                # exponential backoff with jitter
                backoff = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                backoff = backoff + random.uniform(0, 2)
                time.sleep(backoff)
                continue

            if is_network_error_page(driver):
                print("Network error still active. Refreshing and retrying same page...")
                try:
                    driver.refresh()
                except:
                    pass
                # exponential backoff with jitter
                backoff = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                backoff = backoff + random.uniform(0, 2)
                time.sleep(backoff)
                # occasionally recreate the driver mid-run to clear transient state
                if attempt % NETWORK_ERROR_RESTART_THRESHOLD == 0:
                    print("Frequent network problems — restarting driver before next attempt...")
                    try:
                        restart_driver()
                    except Exception:
                        pass
                continue
        except Exception as e:
            print(f"Driver or connection exception encountered: {e}. Restarting driver...")
            restart_driver()
            time.sleep(RETRY_DELAY_SECONDS)
            continue

        return []

    return []

results = load_json(OUTPUT_FILE, [])

seen = set()
for r in results:
    name = clean_text((r.get("name") or "").lower())
    phone = clean_text((r.get("phone") or ""))
    if name and phone:
        seen.add((name, phone))

progress = load_json(PROGRESS_FILE, {})
state_index = int(progress.get("state_index", 0))
page_start = int(progress.get("page", 1))
page = page_start

pages_processed = 0

for i in range(state_index, len(germany_states)):

    state = germany_states[i]
    page = page_start if i == state_index else 1

    print(f"\n========== STATE: {state} ==========")

    empty_pages = 0
    stop_scraper = False

    while True:

        save_json(PROGRESS_FILE, {"state_index": i, "page": page})

        if pages_processed > 0 and pages_processed % 100 == 0:
            print(f"Recreating driver to clear cache after {pages_processed} pages...")
            restart_driver()

        main_containers = load_page_with_retries(state, page)
        pages_processed += 1

        if len(main_containers) == 0:
            print(f"No results found at {state} page {page}")
            save_json(PROGRESS_FILE, {"state_index": i, "page": page})
            driver.quit()
            print("Progress saved. Stop script.")
            exit()

        new_records = 0

        for main in main_containers:
            try:
                try:
                    name = clean_text(main.find_element(
                        By.CSS_SELECTOR,
                        "h2.result-list-entry-title__headline"
                    ).text)
                except:
                    name = None

                try:
                    address = clean_text(main.find_element(
                        By.CSS_SELECTOR,
                        "div.result-list-entry-address"
                    ).text)
                except:
                    address = None

                phone = None
                try:
                    card = main.find_element(
                        By.XPATH,
                        "./ancestor::*[contains(@class,'result-entry')][1]"
                    )
                    phones = card.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
                    if phones:
                        phone = phones[0].get_attribute("href").replace("tel:", "").strip()
                except:
                    pass

                if not name or not phone:
                    continue

                name = clean_text(name).lower()
                phone = clean_text(phone)

                if name == "" or phone == "":
                    continue

                key = (name, phone)
                if key in seen:
                    continue

                seen.add(key)
                results.append({
                    "name": name,
                    "phone": phone,
                    "address": address,
                    "state": state
                })
                new_records += 1

            except:
                continue

        print(f"New records: {new_records}")

        if new_records > 0:
            save_json(OUTPUT_FILE, results)

        if new_records == 0:
            empty_pages += 1
        else:
            empty_pages = 0

        if empty_pages >= 2:
            print("2 empty pages → next state")
            break

        page += 1
        save_json(PROGRESS_FILE, {"state_index": i, "page": page})

    print(f"Completed state: {state}")

driver.quit()

save_json(PROGRESS_FILE, {
    "state_index": len(germany_states),
    "page": page,
    "status": "completed"
})

final_seen = set()
clean_results = []

for r in results:
    name = clean_text((r.get("name") or "").lower())
    phone = clean_text((r.get("phone") or ""))
    if not name or not phone:
        continue
    key = (name, phone)
    if key in final_seen:
        continue
    final_seen.add(key)
    clean_results.append(r)

save_json(OUTPUT_FILE, clean_results)

print("\nDONE — Fully deduplicated flat JSON saved")
