import os
import shutil
import tempfile
import time
import random
import pandas as pd
from datetime import datetime
from math import isnan

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

from selenium.common.exceptions import TimeoutException, WebDriverException


URL = "https://amd-ai-engage.machinehack.com/register"
DATA_FILE = "users.xlsx"

DEBUG_DIR = "debug_screens"
os.makedirs(DEBUG_DIR, exist_ok=True)

# ====== TUNABLES ======
POST_SUBMIT_MAX_WAIT_SECONDS = 90
POST_SUBMIT_POLL_SECONDS = 3
REFRESH_AFTER_STUCK_SECONDS = 45
MAX_REFRESHES_WHEN_STUCK = 2
MANUAL_DELAY_AFTER_SUBMIT = (4, 8)

PAGELOAD_TIMEOUT = 45          # stop get()/refresh() from hanging forever
GET_RETRIES = 2                # retry opening URL if it times out


# =========================
# Driver (fresh profile, no cache reuse)
# =========================
def create_driver():
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")

    fresh_profile_dir = tempfile.mkdtemp(prefix="chrome_profile_")
    options.add_argument(f"--user-data-dir={fresh_profile_dir}")
    options.add_argument("--disk-cache-size=0")
    options.add_argument("--disable-application-cache")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    # prevent infinite page load waits
    driver.set_page_load_timeout(PAGELOAD_TIMEOUT)

    # Best-effort webdriver hiding
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    # Clear cookies/cache via CDP
    try:
        driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    except Exception:
        pass

    driver._fresh_profile_dir = fresh_profile_dir
    return driver


def cleanup_driver(driver):
    profile_dir = getattr(driver, "_fresh_profile_dir", None)
    try:
        driver.quit()
    finally:
        if profile_dir and os.path.exists(profile_dir):
            shutil.rmtree(profile_dir, ignore_errors=True)


# =========================
# Utilities
# =========================
def load_users():
    df = pd.read_excel(DATA_FILE) if not DATA_FILE.endswith(".csv") else pd.read_csv(DATA_FILE)
    if "Status" not in df.columns:
        df["Status"] = ""
    df["Status"] = df["Status"].astype("object")
    return df


def human_delay(a=1.0, b=2.0):
    time.sleep(random.uniform(a, b))


def manual_delay_range(rng):
    a, b = rng
    time.sleep(random.uniform(a, b))


def _clean(v, default=""):
    if v is None:
        return default
    try:
        if isinstance(v, float) and isnan(v):
            return default
    except Exception:
        pass
    if isinstance(v, str):
        return v.strip()
    return v


def dump_debug(driver, tag):
    try:
        img_path = os.path.join(DEBUG_DIR, f"{tag}.png")
        driver.save_screenshot(img_path)
        print(f"🖼 Saved screenshot: {img_path}")
    except Exception:
        pass

    try:
        html_path = os.path.join(DEBUG_DIR, f"{tag}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"📄 Saved HTML: {html_path}")
    except Exception:
        pass

    try:
        print("🌐 Current URL:", driver.current_url)
    except Exception:
        pass


def safe_get(driver, url, tag="get"):
    """Open a URL with retries to avoid hanging forever."""
    for attempt in range(1, GET_RETRIES + 1):
        try:
            driver.get(url)
            return True
        except TimeoutException:
            print(f"⚠ Page load timeout on GET (attempt {attempt}/{GET_RETRIES})")
            dump_debug(driver, f"{tag}_timeout_attempt{attempt}")
            try:
                driver.execute_script("window.stop();")
            except Exception:
                pass
            human_delay(1.0, 2.0)
        except WebDriverException as e:
            print(f"⚠ WebDriverException on GET: {e}")
            dump_debug(driver, f"{tag}_webdriver_exception")
            human_delay(1.0, 2.0)
    return False


def safe_refresh(driver, tag="refresh"):
    try:
        driver.refresh()
        return True
    except TimeoutException:
        print("⚠ Page load timeout on refresh")
        dump_debug(driver, f"{tag}_timeout")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass
        return False
    except Exception:
        return False


# =========================
# Page State Detection
# =========================
def detect_page_state(driver):
    """
    Returns:
      DASHBOARD, TOKEN_PAGE, REGISTER_PAGE, FORM_ERROR,
      ALREADY_REGISTERED, INVALID_TOKEN,
      AMD_LINK_STEP, BLOCKED_OR_CLOUDFLARE, BLOCKED_OR_CAPTCHA, UNKNOWN
    """
    try:
        src = (driver.page_source or "").lower()

        if ("checking your browser" in src or
            "cf-browser-verification" in src or
            "cloudflare" in src or
            "attention required" in src or
            "verify you are human" in src):
            return "BLOCKED_OR_CLOUDFLARE"

        if ("captcha" in src or "recaptcha" in src or "hcaptcha" in src):
            return "BLOCKED_OR_CAPTCHA"

        if driver.find_elements(By.XPATH, "//*[contains(text(),'Welcome back')]"):
            return "DASHBOARD"

        if driver.find_elements(By.XPATH, "//input[contains(@placeholder,'access token') or contains(@placeholder,'token')]"):
            return "TOKEN_PAGE"

        if driver.find_elements(By.XPATH, "//a[contains(.,'Register for the AMD AI Developer Program')]"):
            return "AMD_LINK_STEP"

        if driver.find_elements(By.XPATH, "//*[contains(text(),'already registered') or contains(text(),'User already registered')]"):
            return "ALREADY_REGISTERED"

        if driver.find_elements(By.XPATH, "//*[contains(text(),'Invalid token') or contains(text(),'invalid token')]"):
            return "INVALID_TOKEN"

        if driver.find_elements(By.XPATH, "//input[@placeholder='Enter your full name']"):
            if driver.find_elements(By.XPATH, "//*[contains(text(),'required') or contains(text(),'invalid') or contains(@class,'error') or contains(@class,'toast')]"):
                return "FORM_ERROR"
            return "REGISTER_PAGE"

        return "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def click_amd_link_if_present(driver):
    amd_links = driver.find_elements(By.XPATH, "//a[contains(.,'Register for the AMD AI Developer Program')]")
    if not amd_links:
        return False
    try:
        before = set(driver.window_handles)
        driver.execute_script("arguments[0].click();", amd_links[0])
        human_delay(0.6, 1.2)

        after = set(driver.window_handles)
        new_tabs = list(after - before)
        if new_tabs:
            driver.switch_to.window(new_tabs[0])
            driver.close()
            driver.switch_to.window(driver.window_handles[0])
        return True
    except Exception:
        return False


# =========================
# Wait for next step (NO aggressive refresh)
# =========================
def wait_until_token_or_dashboard(driver, max_wait=POST_SUBMIT_MAX_WAIT_SECONDS):
    start = time.time()
    last_progress = time.time()
    refreshes = 0

    while (time.time() - start) < max_wait:
        state = detect_page_state(driver)
        elapsed = int(time.time() - start)
        print(f"🧭 State: {state} | elapsed={elapsed}s")

        if state in ("TOKEN_PAGE", "DASHBOARD", "ALREADY_REGISTERED", "FORM_ERROR",
                     "BLOCKED_OR_CLOUDFLARE", "BLOCKED_OR_CAPTCHA", "INVALID_TOKEN"):
            return state

        if state == "AMD_LINK_STEP":
            clicked = click_amd_link_if_present(driver)
            if clicked:
                last_progress = time.time()
            time.sleep(2)
            continue

        # UNKNOWN -> wait and allow SPA to load
        time.sleep(POST_SUBMIT_POLL_SECONDS)

        stuck_for = time.time() - last_progress
        if stuck_for >= REFRESH_AFTER_STUCK_SECONDS and refreshes < MAX_REFRESHES_WHEN_STUCK:
            refreshes += 1
            print(f"🔁 Stuck for {int(stuck_for)}s → refreshing ({refreshes}/{MAX_REFRESHES_WHEN_STUCK})")
            ok = safe_refresh(driver, tag=f"post_submit_refresh_row")
            last_progress = time.time() if ok else last_progress

    return "TIMEOUT"


# =========================
# After token submit, confirm success / invalid
# =========================
def wait_for_submission_result(driver, timeout=25):
    wait = WebDriverWait(driver, timeout)

    def _ready(d):
        return bool(
            d.find_elements(By.XPATH, "//*[contains(text(),'Invalid token') or contains(text(),'invalid token')]")
            or d.find_elements(By.XPATH, "//*[contains(text(),'Welcome back')]")
        )

    try:
        wait.until(_ready)
    except TimeoutException:
        return "unknown"

    if driver.find_elements(By.XPATH, "//*[contains(text(),'Invalid token') or contains(text(),'invalid token')]"):
        return "invalid"
    if driver.find_elements(By.XPATH, "//*[contains(text(),'Welcome back')]"):
        return "success"
    return "unknown"


# =========================
# Process one user
# =========================
def process_user(driver, user, index):
    wait = WebDriverWait(driver, 30)

    name = _clean(user.get("name"))
    email = _clean(user.get("email"))
    password = _clean(user.get("password"))
    college = _clean(user.get("college"))
    city = _clean(user.get("city"))
    phone = _clean(user.get("phone"))
    access_token = _clean(user.get("access_token"))

    print(f"\n🚀 Processing row {index + 1} - {email}")

    if not all([name, email, password, college, city, phone, access_token]):
        return "Missing Data"

    ok = safe_get(driver, URL, tag=f"row{index+1}_open_register")
    if not ok:
        return "Page Load Timeout"

    # --- Page 1 fields
    wait.until(EC.presence_of_element_located(
        (By.XPATH, "//input[@placeholder='Enter your full name']")
    )).send_keys(name)

    driver.find_element(By.XPATH, "//input[@placeholder='Enter your email']").send_keys(email)
    driver.find_element(By.XPATH, "//input[@placeholder='Create a password']").send_keys(password)
    driver.find_element(By.XPATH, "//input[@placeholder='Confirm your password']").send_keys(password)
    driver.find_element(By.XPATH, "//input[@placeholder='Enter your college or company']").send_keys(college)

    # City dropdown (exact then partial)
    location_el = driver.find_element(By.NAME, "location")
    sel = Select(location_el)
    try:
        sel.select_by_visible_text(city)
    except Exception:
        options_text = [o.text.strip() for o in sel.options]
        match = next((t for t in options_text if city.lower() in t.lower()), None)
        if match:
            sel.select_by_visible_text(match)
        else:
            dump_debug(driver, f"row{index+1}_invalid_city")
            return "Invalid City"

    driver.find_element(By.XPATH, "//input[@placeholder='10-digit number']").send_keys(str(phone))

    driver.find_element(By.XPATH, "//input[@type='checkbox']").click()
    driver.find_element(By.XPATH, "//button[@type='submit']").click()

    # Manual human pause after submit
    manual_delay_range(MANUAL_DELAY_AFTER_SUBMIT)

    # --- Wait for token/dashboard
    state = wait_until_token_or_dashboard(driver, max_wait=POST_SUBMIT_MAX_WAIT_SECONDS)

    if state == "ALREADY_REGISTERED":
        return "User Already Registered"

    if state == "FORM_ERROR":
        dump_debug(driver, f"row{index+1}_form_error")
        return "Form Error"

    if state in ("BLOCKED_OR_CLOUDFLARE", "BLOCKED_OR_CAPTCHA"):
        dump_debug(driver, f"row{index+1}_blocked")
        return "Blocked/Captcha"

    if state == "DASHBOARD":
        return "Successful"

    if state != "TOKEN_PAGE":
        dump_debug(driver, f"row{index+1}_token_not_found_{state.lower()}")
        return "Token Page Not Found"

    # --- TOKEN PAGE: submit token
    def submit_token():
        token_input = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[contains(@placeholder,'access token') or contains(@placeholder,'token')]")
            )
        )
        token_input.clear()
        token_input.send_keys(str(access_token))
        driver.find_element(By.XPATH, "//button[contains(.,'Complete')]").click()
        manual_delay_range((2, 4))

    try:
        submit_token()
    except Exception:
        dump_debug(driver, f"row{index+1}_token_submit_error")
        return "Error"

    # --- Verify result
    result = wait_for_submission_result(driver, timeout=30)
    if result == "invalid":
        return "Invalid Token"
    if result == "success":
        return "Successful"

    dump_debug(driver, f"row{index+1}_submission_unknown")
    return "Submission Unconfirmed"


# =========================
# MAIN (new browser per user)
# =========================
def main():
    df = load_users()

    for index, user in df.iterrows():
        driver = create_driver()
        try:
            status = process_user(driver, user, index)
            df.at[index, "Status"] = status
        except WebDriverException as e:
            print(f"❌ WebDriver error on row {index + 1}: {e}")
            df.at[index, "Status"] = "WebDriver Error"
        except Exception as e:
            print(f"❌ Unexpected error on row {index + 1}: {e}")
            df.at[index, "Status"] = "Error"
        finally:
            cleanup_driver(driver)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"users_updated_{timestamp}.xlsx"
    df.to_excel(output_file, index=False)

    print(f"\n📄 Results saved to {output_file}")
    print("\n✅ Processing Completed.\n")


if __name__ == "__main__":
    main()