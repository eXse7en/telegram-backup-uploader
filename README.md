# Telegram Backup Auto Uploader 🚀

Script Python untuk **meng-upload file backup secara otomatis ke Telegram** ketika file `.zip` muncul di folder tertentu.

✅ Support **Local Telegram Bot API**  
✅ Bisa upload **file besar hingga ±2GB tanpa split**  
✅ Jalan otomatis via **systemd (auto start setelah reboot)**  
✅ Cocok untuk backup server / website / database  

---

## 📌 Fitur Utama

- Monitor folder backup secara real-time (watchdog)
- Upload otomatis ke Telegram (channel / group)
- Support **Local Bot API** untuk upload file besar
- Fallback ke **Cloud Bot API** (dengan split file)
- Anti error race-condition (file belum selesai ditulis / rename)
- Auto cleanup file setelah upload sukses
- Aman untuk production (jalan sebagai service)

---

## 🧱 Arsitektur

```
/var/www/html/sirama
├── backup/                     # Folder backup (dipantau)
│   └── *.zip
└── telegram-backup-uploader/
    ├── app/
    │   ├── auto_upload_telegram.py
    │   ├── .env
    │   └── .venv/
    ├── docker-compose.yml
    ├── .env.botapi
    └── README.md
```

---

## 📋 Requirement

### System
- Linux (Ubuntu/Debian direkomendasikan)
- Python ≥ 3.9
- Docker & Docker Compose
- Akses sudo

### Python Package
- python-dotenv
- watchdog
- requests
- tqdm
- requests-toolbelt

---

## 🔐 Persiapan Telegram

### 1️⃣ Buat Bot Telegram
- Chat ke **@BotFather**
- Buat bot → dapatkan **BOT TOKEN**
- Tambahkan bot ke **channel**
- Jadikan bot **admin** (izin kirim media)

Catat:
- `API_TOKEN`
- `CHAT_ID` (format: `-100xxxxxxxxxx`)

---

### 2️⃣ Ambil api_id & api_hash (WAJIB untuk Local Bot API)
Digunakan oleh **server Bot API**, bukan script Python.

1. Buka https://my.telegram.org
2. Login
3. Pilih **API development tools**
4. Buat aplikasi
5. Catat:
   - `api_id`
   - `api_hash`

---

## ⚙️ Setup Project

### 1️⃣ Buat folder kerja
```bash
mkdir -p /var/www/html/sirama/telegram-backup-uploader/app
mkdir -p /var/www/html/sirama/backup
```

---

### 2️⃣ File `.env` (untuk script Python)
Lokasi:
```
telegram-backup-uploader/app/.env
```

Isi:
```env
API_TOKEN=ISI_TOKEN_BOT
CHAT_ID=-100XXXXXXXXXX

UPLOAD_DIR=/var/www/html/sirama/backup

USE_LOCAL_BOT_API=1
BOT_API_BASE=http://127.0.0.1:8081

MAX_LOCAL_MB=2000
MAX_CLOUD_MB=49
```

Amankan:
```bash
chmod 600 app/.env
```

---

### 3️⃣ File `.env.botapi` (untuk Docker Bot API)
Lokasi:
```
telegram-backup-uploader/.env.botapi
```

Isi:
```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef
```

---

### 4️⃣ `docker-compose.yml`
```yaml
services:
  telegram-bot-api:
    image: aiogram/telegram-bot-api:latest
    container_name: telegram-bot-api
    restart: unless-stopped
    ports:
      - "8081:8081"
    env_file:
      - .env.botapi
    command:
      - "--local"
      - "--http-port=8081"
      - "--dir=/var/lib/telegram-bot-api"
    volumes:
      - telegram_bot_api_data:/var/lib/telegram-bot-api
      - /var/www/html/sirama/backup:/var/www/html/sirama/backup:ro

volumes:
  telegram_bot_api_data:
```

Jalankan:
```bash
docker compose up -d
```

---

## 🐍 Setup Python Environment

```bash
cd telegram-backup-uploader/app
python3 -m venv .venv
source .venv/bin/activate
pip install python-dotenv watchdog requests tqdm requests-toolbelt
deactivate
```

---

## ▶️ Test Manual

```bash
source app/.venv/bin/activate
python app/auto_upload_telegram.py
```

Terminal lain:
```bash
cd /var/www/html/sirama/backup
zip -r test_backup.zip /etc/hosts >/dev/null
```

---

## ⚙️ systemd Service

### Buat service
```bash
sudo nano /etc/systemd/system/telegram-backup-uploader.service
```

Isi:
```ini
[Unit]
Description=Telegram Backup Auto Uploader (Local Bot API)
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
WorkingDirectory=/var/www/html/sirama/telegram-backup-uploader/app
EnvironmentFile=/var/www/html/sirama/telegram-backup-uploader/app/.env
ExecStart=/var/www/html/sirama/telegram-backup-uploader/app/.venv/bin/python /var/www/html/sirama/telegram-backup-uploader/app/auto_upload_telegram.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Aktifkan:
```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-backup-uploader
sudo systemctl start telegram-backup-uploader
```

---

## 🧪 Test Otomatis

```bash
cd /var/www/html/sirama/backup
zip -r test_backup_$(date +%F_%H%M%S).zip /etc/hosts >/dev/null
```

Pantau log:
```bash
sudo journalctl -u telegram-backup-uploader -f
```

---

## 🔒 Security Notes

Tambahkan ke `.gitignore`:
```gitignore
.env
.env.botapi
.venv/
```

---

## 📜 License
MIT License

---

Happy backup! 🚀
