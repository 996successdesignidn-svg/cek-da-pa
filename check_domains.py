import os
import requests
import traceback

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException


VERSION = "cekdapa-final-v2"
TARGET_URL = "https://cekdapa.com/cek-nawala/"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}
    requests.post(url, json=payload, timeout=20)


def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1280,720")

    # bikin lebih “mirip browser normal”
    options.add_argument(
        "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def load_domains():
    if not DOMAINS_ENV.strip():
        return []
    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def normalize_input(dom: str) -> str:
    d = dom.strip()
    if not d:
        return d
    d = d.replace("https://", "").replace("http://", "").strip()
    return "https://" + d


def clean_key(text: str) -> str:
    return text.replace("https://", "").replace("http://", "").strip().lower()


def find_cek_nawala_button(driver):
    # tombol bisa button/a/input
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
        if "terblokir" in (t or "").strip().lower():
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

    # Tunggu salah satu terjadi:
    # - baris hasil tabel muncul
    # - teks error muncul ("Respon API tidak valid")
    def done(d):
        body = d.find_element(By.TAG_NAME, "body").text.lower()
        if "respon api tidak valid" in body or "error - respon api tidak valid" in body:
            return "API_INVALID"
        if len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0:
            return "HAS_ROWS"
        return False

    state = wait.until(done)

    if state == "API_INVALID":
        raise RuntimeError("CekDAPA menampilkan: Error - Respon API tidak valid")

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


def main():
    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (cekdapa) [{VERSION}]\nTidak ada domain.")
        return

    # tanda hidup biar kamu yakin job jalan
    send_telegram(f"▶️ Running CekDAPA checker [{VERSION}] (domains: {len(domains)})")

    driver = setup_driver()
    final = {}

    try:
        for batch in chunk(domains, 5):
            res = check_batch(driver, batch)
            final.update(res)

    except TimeoutException as e:
        # biasanya karena tabel tidak muncul (kemungkinan diblokir / IP luar / anti-bot)
        info = f"❌ Timeout (cekdapa) [{VERSION}]\nURL: {driver.current_url}\nTitle: {driver.title}"
        send_telegram(info)
        print(info, flush=True)
        traceback.print_exc()

    except Exception as e:
        info = f"❌ Gagal cek (cekdapa) [{VERSION}]\n{type(e).__name__}: {e}\nURL: {driver.current_url}\nTitle: {driver.title}"
        send_telegram(info)
        print(info, flush=True)
        traceback.print_exc()

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # kalau final kosong, stop
    if not final:
        return

    lines = [f"Domain Status Report (cekdapa) [{VERSION}]"]
    for d in domains:
        key = clean_key(d)
        blocked = final.get(key, False)
        lines.append(f"{key}: {'🔴 Blocked' if blocked else '🟢 Not Blocked'}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
