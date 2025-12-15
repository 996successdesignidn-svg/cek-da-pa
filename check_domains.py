import os
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

VERSION = "cekdapa-v1"
TARGET_URL = "https://cekdapa.com/cek-nawala/"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram env belum di-set")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}

    resp = requests.post(url, json=payload, timeout=20)
    print("Telegram resp:", resp.status_code, resp.text[:200])


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


def load_domains():
    if not DOMAINS_ENV.strip():
        return []

    raw = DOMAINS_ENV.replace("\n", ",")
    parts = [p.strip() for p in raw.split(",")]
    domains = [p for p in parts if p]
    return domains


def chunk(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def normalize_input(dom: str) -> str:
    """
    Cekdapa menerima URL/domain.
    Dari screenshot kamu pakai https://domain
    Jadi kita rapikan: kalau user input domain saja, kita tambahkan https://
    """
    d = dom.strip()
    if not d:
        return d
    if d.startswith("http://") or d.startswith("https://"):
        return d
    return "https://" + d


def row_is_blocked(cells_text: list[str]) -> bool:
    """
    Jika ada sel yang mengandung kata 'Terblokir' -> dianggap blocked.
    """
    for t in cells_text:
        if "terblokir" in (t or "").strip().lower():
            return True
    return False


def check_batch_cekdapa(driver, domains_batch: list[str]) -> dict:
    """
    Return dict:
      key: domain tanpa protokol (misal boxing55a.live)
      value: (blocked_bool, detail_cells)
    """
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)

    # 1) cari textarea input (di halaman ini biasanya hanya satu)
    textarea = wait.until(lambda d: d.find_element(By.TAG_NAME, "textarea"))
    textarea.clear()
    textarea.send_keys("\n".join(normalize_input(x) for x in domains_batch))

    # 2) klik tombol "Cek Nawala"
    btn = wait.until(
        lambda d: d.find_element(By.XPATH, "//button[contains(., 'Cek Nawala')]")
    )
    btn.click()

    # 3) tunggu tabel "Hasil Cek" muncul
    # kita cari baris tabel setelah judul "Hasil Cek"
    wait.until(lambda d: len(d.find_elements(By.XPATH, "//h2[contains(.,'Hasil Cek')]/following::table[1]//tbody/tr")) > 0)

    rows = driver.find_elements(By.XPATH, "//h2[contains(.,'Hasil Cek')]/following::table[1]//tbody/tr")
    results = {}

    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) < 2:
            continue

        domain_text = tds[0].text.strip()
        # domain kadang tampil tanpa https://, kita bikin key yang konsisten:
        key = domain_text.replace("https://", "").replace("http://", "").strip().lower()

        cells = [td.text.strip() for td in tds[1:]]  # kolom status provider
        blocked = row_is_blocked(cells)
        results[key] = (blocked, cells)

    return results


def main():
    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report ({VERSION})\nTidak ada domain untuk dicek.")
        return

    driver = setup_driver()
    final = {}

    try:
        # cekdapa max 5 per request
        for batch in chunk(domains, 5):
            batch_res = check_batch_cekdapa(driver, batch)
            final.update(batch_res)
    except Exception as e:
        try:
            driver.quit()
        except Exception:
            pass
        send_telegram(f"❌ Gagal cek (cekdapa) [{VERSION}]: {e}")
        return

    try:
        driver.quit()
    except Exception:
        pass

    lines = [f"Domain Status Report (cekdapa) [{VERSION}]"]

    for d in domains:
        key = d.strip().lower().replace("https://", "").replace("http://", "")
        blocked, _cells = final.get(key, (False, []))
        if blocked:
            lines.append(f"{key}: 🔴 Blocked")
        else:
            lines.append(f"{key}: 🟢 Not Blocked")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
