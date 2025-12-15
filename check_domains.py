import os
import traceback
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


VERSION = "cekdapa-v2"
TARGET_URL = "https://cekdapa.com/cek-nawala/"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DOMAINS_ENV = os.environ.get("DOMAINS_TO_CHECK", "")


def send_telegram(text: str):
    """Kirim pesan Telegram (plain text)."""
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
        resp = requests.post(url, json=payload, timeout=20)
        print("Telegram resp:", resp.status_code, resp.text[:200], flush=True)
    except Exception as e:
        print("Gagal kirim Telegram:", e, flush=True)


def setup_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1280,720")
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
        yield lst[i:i + n]


def normalize_input(dom: str) -> str:
    """
    CekDAPA menerima URL/Domain. Supaya konsisten:
    - Jika input belum ada http/https -> tambahkan https://
    """
    d = dom.strip()
    if not d:
        return d
    if d.startswith("http://") or d.startswith("https://"):
        return d
    return "https://" + d


def row_is_blocked(cells_text: list[str]) -> bool:
    """Jika ada sel mengandung 'Terblokir' maka blocked."""
    for t in cells_text:
        if "terblokir" in (t or "").strip().lower():
            return True
    return False


def find_button_cek_nawala(driver):
    """
    Tombol bisa berupa <button>, <a>, atau <input>.
    Cari elemen yang visible dan mengandung teks/value 'Cek Nawala'.
    """
    # 1) button / a yang berisi teks
    candidates = driver.find_elements(
        By.XPATH,
        "//*[self::button or self::a][contains(normalize-space(.), 'Cek Nawala')]"
    )
    for el in candidates:
        try:
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            pass

    # 2) input type submit/button yang value-nya "Cek Nawala"
    candidates = driver.find_elements(
        By.XPATH,
        "//input[(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ')='CEK NAWALA') "
        "or contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CEK NAWALA')]"
    )
    for el in candidates:
        try:
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            pass

    raise RuntimeError("Tombol 'Cek Nawala' tidak ditemukan")


def check_batch_cekdapa(driver, domains_batch: list[str]) -> dict:
    """
    Return dict:
      key: domain tanpa protokol (lowercase)
      value: blocked_bool
    """
    driver.get(TARGET_URL)
    wait = WebDriverWait(driver, 40)

    wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))

    # textarea pertama di halaman
    textarea = wait.until(lambda d: d.find_element(By.TAG_NAME, "textarea"))
    textarea.clear()
    textarea.send_keys("\n".join(normalize_input(x) for x in domains_batch))

    # klik tombol
    btn = wait.until(lambda d: find_button_cek_nawala(d))
    btn.click()

    # tunggu tabel hasil muncul (cara umum)
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "table tbody tr")) > 0)

    rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
    results = {}

    for row in rows:
        tds = row.find_elements(By.TAG_NAME, "td")
        if len(tds) < 2:
            continue

        domain_text = tds[0].text.strip()
        key = (
            domain_text.replace("https://", "")
            .replace("http://", "")
            .strip()
            .lower()
        )

        cells = [td.text.strip() for td in tds[1:]]
        blocked = row_is_blocked(cells)
        results[key] = blocked

    return results


def main():
    domains = load_domains()
    if not domains:
        send_telegram(f"Domain Status Report (cekdapa) [{VERSION}]\nTidak ada domain untuk dicek.")
        return

    driver = setup_driver()
    final_results = {}

    try:
        # cekdapa max 5 domain per request
        for batch in chunk(domains, 5):
            batch_res = check_batch_cekdapa(driver, batch)
            final_results.update(batch_res)

    except Exception as e:
        # debug lengkap ke logs
        print("=== ERROR ===", flush=True)
        print("VERSION:", VERSION, flush=True)
        try:
            print("Current URL:", driver.current_url, flush=True)
            print("Title:", driver.title, flush=True)
        except Exception:
            pass
        print("ERROR TYPE:", type(e).__name__, flush=True)
        print("ERROR MSG:", str(e), flush=True)
        traceback.print_exc()

        # screenshot & html untuk investigasi (kalau environment mengizinkan)
        try:
            driver.save_screenshot("/tmp/cekdapa_error.png")
            with open("/tmp/cekdapa_error.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved debug: /tmp/cekdapa_error.png and /tmp/cekdapa_error.html", flush=True)
        except Exception as e2:
            print("Gagal simpan debug file:", e2, flush=True)

        try:
            driver.quit()
        except Exception:
            pass

        send_telegram(f"❌ Gagal cek (cekdapa) [{VERSION}]: {type(e).__name__}: {e}")
        return

    try:
        driver.quit()
    except Exception:
        pass

    lines = [f"Domain Status Report (cekdapa) [{VERSION}]"]

    for d in domains:
        key = d.strip().lower().replace("https://", "").replace("http://", "")
        blocked = final_results.get(key, False)
        lines.append(f"{key}: {'🔴 Blocked' if blocked else '🟢 Not Blocked'}")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    main()
