import os
import traceback
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


VERSION = "cekdapa-final-v1"
TARGET_URL = "https://cekdapa.com/cek-nawala/"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


# ================= TELEGRAM =================
def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set", flush=True)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        print("Telegram resp:", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("Gagal kirim Telegram:", e, flush=True)


# ================= SELENIUM =================
def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


# ================= DOMAIN =================
def load_domains():
    if not DOMAINS_ENV.strip():
        return []
    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def normalize_input(dom: str) -> str:
    """
    FIX UTAMA:
    CekDAPA HARUS URL.
    Walaupun ENV hanya domain.com → paksa jadi https://domain.com
    """
    d = dom.strip()
    if not d:
        return d
    d = d.replace("https://", "").replace("http://", "").strip()
    return "https://" + d


def clean_key(text: str) -> str:
    return text.replace("https://", "").replace("http://", "").strip().lower()


# ================= CEKDAPA CORE =================
def find_cek_nawala_button(driver):
    # tombol bisa button / a / input
    xpath = (
        "//*[self::button or self::a or self::input]"
        "[contains(normalize-space(.), 'Cek Nawala') or @value='Cek Nawala']"
    )
    elems = driver.find_elements(By.XPATH, xpath)
    for el in elems:
        try:
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            pass
    raise RuntimeError("Tombol 'Cek Nawala' tidak ditemukan")


def row_is_blocked(cells):
    for t in cells:
        if "terblokir" in t.lower():
            return True
    return False


def check_batch(driver, batch):
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)

    wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

    textarea = wait.until(lambda d: d.find_element(By.TAG_NAME, "textarea"))
    textarea.clear()
    textarea.send_keys("\n".join(normalize_input(x) for x in batch))

    btn = wait.until(lambda d: find_cek_nawala_button(d))
    btn.click()

    # tunggu tabel hasil
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0)

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    results = {}

    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) < 2:
            continue

        domain = clean_key(tds[0].text)
        cells = [td.text.strip() for td in tds[1:]]
        results[domain] = row_is_blocked(cells)

    return results


# ================= MAIN =================
def main():
    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (cekdapa)\nTidak ada domain.")
        return

    driver = setup_driver()
    final = {}

    try:
        for batch in chunk(domains, 5):  # limit cekdapa
            res = check_batch(driver, batch)
            final.update(res)

    except Exception as e:
        print("ERROR:", type(e).__name__, str(e), flush=True)
        traceback.print_exc()

        try:
            print("URL:", driver.current_url, "TITLE:", driver.title, flush=True)
        except Exception:
            pass

        try:
            driver.quit()
        except Exception:
            pass

        send_telegram(
            f"❌ Gagal cek (cekdapa)\n"
            f"Versi: {VERSION}\n"
            f"Error: {type(e).__name__}: {e}"
        )
        return

    try:
        driver.quit()
    except Exception:
        pass

    # ===== TELEGRAM OUTPUT =====
    lines = [f"Domain Status Report (cekdapa) [{VERSION}]"]

    for d in domains:
        key = clean_key(d)
        blocked = final.get(key, False)
        lines.append(f"{key}: {'🔴 Blocked' if blocked else '🟢 Not Blocked'}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
