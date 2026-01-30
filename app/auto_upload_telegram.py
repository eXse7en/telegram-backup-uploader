import os
import time
import logging
import requests
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from tqdm import tqdm
from requests_toolbelt import MultipartEncoder, MultipartEncoderMonitor

# =========================
# 1) Load Config
# =========================
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./folder_upload")

BOT_API_BASE = os.getenv("BOT_API_BASE", "https://api.telegram.org").rstrip("/")
USE_LOCAL = os.getenv("USE_LOCAL_BOT_API", "0") == "1"

MAX_CLOUD_MB = int(os.getenv("MAX_CLOUD_MB", "49"))
MAX_LOCAL_MB = int(os.getenv("MAX_LOCAL_MB", "2000"))

CHUNK_SIZE = MAX_CLOUD_MB * 1024 * 1024
TELEGRAM_API = f"{BOT_API_BASE}/bot{API_TOKEN}"

os.makedirs(UPLOAD_DIR, exist_ok=True)

# =========================
# 2) Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# =========================
# 3) Telegram helpers
# =========================
def send_message(text: str):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            data={"chat_id": str(CHAT_ID), "text": text},
            timeout=30
        )
    except Exception as e:
        logging.error(f"Gagal kirim pesan: {e}")

# =========================
# 4) File helpers
# =========================
def wait_for_exists(path: str, timeout_sec: int = 15, interval: float = 0.5) -> bool:
    """Tunggu file benar-benar muncul (untuk event moved/rename yang kadang race)."""
    end = time.time() + timeout_sec
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(interval)
    return False

def wait_until_stable(path: str, interval: float = 1.0, checks: int = 3, timeout_sec: int = 120) -> bool:
    """
    Tunggu file stabil (ukuran tidak berubah) dan masih ada.
    Return True jika stabil, False jika file hilang/timeout.
    """
    if not wait_for_exists(path, timeout_sec=15, interval=0.5):
        logging.warning(f"File tidak ditemukan (tidak muncul): {path}")
        return False

    end = time.time() + timeout_sec
    last = -1
    stable = 0

    while time.time() < end:
        try:
            size = os.path.getsize(path)
        except FileNotFoundError:
            logging.warning(f"File hilang saat menunggu stabil: {path}")
            return False

        if size == last:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0

        last = size
        time.sleep(interval)

    logging.warning(f"Timeout menunggu file stabil: {path}")
    return False

def split_file(path: str):
    parts = []
    with open(path, "rb") as f:
        i = 1
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            part = f"{path}.part{i}"
            with open(part, "wb") as p:
                p.write(chunk)
            parts.append(part)
            i += 1
    return parts

# =========================
# 5) Upload logic
# =========================
def upload_file_multipart(path: str, caption: str) -> bool:
    name = os.path.basename(path)

    try:
        with open(path, "rb") as f:
            encoder = MultipartEncoder(
                fields={
                    "chat_id": str(CHAT_ID),
                    "caption": caption,
                    "document": (name, f, "application/octet-stream"),
                    "disable_content_type_detection": "true",
                }
            )

            with tqdm(total=encoder.len, unit="B", unit_scale=True, desc=f"Uploading {name}") as bar:
                def cb(m):
                    bar.update(m.bytes_read - bar.n)

                monitor = MultipartEncoderMonitor(encoder, cb)
                headers = {"Content-Type": monitor.content_type}

                r = requests.post(
                    f"{TELEGRAM_API}/sendDocument",
                    data=monitor,
                    headers=headers,
                    timeout=3600
                )

        if r.status_code != 200:
            logging.error(f"Upload gagal: HTTP {r.status_code} - {r.text[:500]}")
            return False
        return True

    except FileNotFoundError:
        logging.warning(f"File sudah tidak ada saat mau upload: {path}")
        return False
    except Exception as e:
        logging.error(f"Upload exception: {e}")
        return False

# =========================
# 6) Watchdog handler
# =========================
class FileHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        # dedup event: path -> last_time
        self._seen = {}
        self._dedup_seconds = 5

    def _should_skip(self, path: str) -> bool:
        now = time.time()
        last = self._seen.get(path, 0)
        self._seen[path] = now
        return (now - last) < self._dedup_seconds

    def handle_zip(self, path: str):
        name = os.path.basename(path)

        if not name.lower().endswith(".zip"):
            return

        # Dedup untuk menghindari double event created+moved
        if self._should_skip(path):
            return

        # Tunggu file siap
        if not wait_until_stable(path):
            return

        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
        except FileNotFoundError:
            logging.warning(f"File hilang sebelum hitung size: {path}")
            return

        mode = "LOCAL" if USE_LOCAL else "CLOUD"
        send_message(f"📦 Backup terdeteksi: {name}\nUkuran: {size_mb:.1f} MB\nMode: {mode}")

        ok = False

        if USE_LOCAL:
            # LOCAL: multipart langsung tanpa split
            if size_mb > MAX_LOCAL_MB:
                send_message(f"❌ Gagal: ukuran {size_mb:.1f} MB melebihi batas LOCAL {MAX_LOCAL_MB} MB")
                return
            ok = upload_file_multipart(path, caption=name)
        else:
            # CLOUD: split kalau besar
            if size_mb > MAX_CLOUD_MB:
                parts = split_file(path)
                total = len(parts)
                ok_all = True
                for i, part in enumerate(parts, 1):
                    cap = f"{name} (part {i}/{total})"
                    if not upload_file_multipart(part, caption=cap):
                        ok_all = False
                        break
                ok = ok_all
            else:
                ok = upload_file_multipart(path, caption=name)

        if ok:
            send_message(f"✅ Backup berhasil diunggah: {name}")
            self.cleanup(path)
        else:
            send_message(f"❌ Backup gagal: {name}")

    def cleanup(self, path: str):
        try:
            if os.path.exists(path):
                os.remove(path)

            dirn = os.path.dirname(path)
            base = os.path.basename(path)
            for fn in os.listdir(dirn):
                if fn.startswith(base + ".part"):
                    os.remove(os.path.join(dirn, fn))

            logging.info("Cleanup selesai (file & part dihapus).")
        except Exception as e:
            logging.error(f"Gagal cleanup: {e}")

    def on_created(self, event):
        if not event.is_directory:
            self.handle_zip(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            # event.dest_path kadang belum ada saat callback; sudah ditangani oleh wait_for_exists
            self.handle_zip(event.dest_path)

# =========================
# 7) Main
# =========================
if __name__ == "__main__":
    if not API_TOKEN or not CHAT_ID:
        raise SystemExit("API_TOKEN / CHAT_ID belum di-set di .env")

    observer = Observer()
    observer.schedule(FileHandler(), UPLOAD_DIR, recursive=False)
    observer.start()

    logging.info(f"Monitoring folder: {UPLOAD_DIR}")
    logging.info(f"Bot API Base: {BOT_API_BASE} | Mode: {'LOCAL' if USE_LOCAL else 'CLOUD'}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        logging.info("Dihentikan (Ctrl+C).")

    observer.join()
