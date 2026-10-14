# Telegram Anti-Spam Bot

Bot grup Telegram berbasis Python + aiogram 3 + SQLite, dengan dashboard admin Flask.

## Fitur
- Deteksi flood dan pesan berulang.
- Anti-link dengan daftar domain yang diizinkan.
- Filter kata terlarang.
- Warning, mute otomatis, dan ban otomatis setelah ambang yang dikonfigurasi.
- Perintah admin `/warn`, `/mute`, `/ban`, `/unmute`, `/unban`, `/stats`.
- Dashboard login untuk konfigurasi dan statistik.
- SQLite menyimpan pengaturan, warning, dan riwayat pelanggaran.

## 1. Buat bot
1. Buka https://t.me/BotFather.
2. Kirim `/newbot`, ikuti instruksi, lalu salin token.
3. Jangan kirim token ke siapa pun dan jangan masukkan token ke Git.

## 2. Tambahkan ke grup
1. Tambahkan bot ke grup Telegram.
2. Promosikan menjadi admin.
3. Beri izin **Delete messages** dan **Restrict members**. Izin ini diperlukan untuk hapus pesan, mute, dan ban.
4. Agar bot menerima pesan grup yang bukan perintah, buka BotFather → `/setprivacy` → pilih bot → `Disable`. Jika mengubah privacy mode, keluarkan lalu tambahkan kembali bot ke grup, atau pastikan konfigurasi diterapkan.
5. Untuk tindakan mute/ban, gunakan supergroup Telegram. Jika perlu, konversi grup ke supergroup.

## 3. Instal di VPS Ubuntu/Debian
Contoh di bawah menggunakan user layanan `antispam`.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
sudo useradd --system --create-home --home-dir /opt/telegram-anti-spam-bot --shell /usr/sbin/nologin antispam
sudo mkdir -p /opt/telegram-anti-spam-bot
sudo chown -R "$USER":"$USER" /opt/telegram-anti-spam-bot
```

Upload/ekstrak semua file ke `/opt/telegram-anti-spam-bot`, lalu:

```bash
cd /opt/telegram-anti-spam-bot
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
nano .env
```

Isi `BOT_TOKEN`, `DASHBOARD_PASSWORD` (minimal 16 karakter), dan `FLASK_SECRET_KEY` (minimal 32 karakter). Buat secret acak dengan:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Jalankan perintah tersebut dua kali untuk menghasilkan secret dashboard dan Flask yang berbeda. Pastikan `.env` hanya dapat dibaca user layanan. Untuk menyederhanakan langkah awal, jalankan manual terlebih dahulu:

```bash
python bot.py
```

Di terminal lain:

```bash
cd /opt/telegram-anti-spam-bot
.venv/bin/python dashboard.py
```

Dashboard default hanya tersedia di `127.0.0.1:8080`. Dari komputer sendiri, buat SSH tunnel:
```bash
ssh -L 8080:127.0.0.1:8080 USER_VPS@IP_VPS
```
Lalu buka `http://127.0.0.1:8080`. Jangan membuka dashboard publik tanpa HTTPS, pembatasan akses, dan konfigurasi reverse proxy yang aman.

## 4. Jalankan sebagai service 24/7
Salin file service ke `/etc/systemd/system/`. Pastikan file proyek ada di `/opt/telegram-anti-spam-bot` dan pemilik file dapat menulis database.

```bash
sudo cp telegram-antispam-bot.service /etc/systemd/system/
sudo cp telegram-antispam-dashboard.service /etc/systemd/system/
sudo chown -R antispam:antispam /opt/telegram-anti-spam-bot
sudo chmod 600 /opt/telegram-anti-spam-bot/.env
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-antispam-bot
sudo systemctl enable --now telegram-antispam-dashboard
sudo systemctl status telegram-antispam-bot
sudo journalctl -u telegram-antispam-bot -f
```

Periksa log dashboard dengan:
```bash
sudo journalctl -u telegram-antispam-dashboard -f
```

## 5. Perintah admin di grup
- Balas pesan anggota dengan `/warn`
- Balas pesan anggota dengan `/mute` atau `/mute 30`
- Balas pesan anggota dengan `/ban`
- Balas pesan anggota dengan `/unmute`
- `/unban USER_ID`
- `/stats`

Perintah moderasi hanya bisa digunakan oleh admin grup. Bot tidak memoderasi admin lain.

## 6. Pengaturan awal
Buka dashboard, lalu atur:
- `anti_link`: aktif/nonaktif.
- Kata terlarang: satu per baris.
- Domain yang diizinkan: satu per baris, misalnya `t.me`.
- Batas flood dan pesan duplikat.
- Jumlah warning sebelum mute/ban dan durasi mute.

## Catatan penting
- SQLite cocok untuk satu VPS dan satu proses bot. Jangan menjalankan dua polling process memakai token yang sama; Telegram hanya mengizinkan satu polling process per token.
- Anti-link berbasis teks/URL sederhana; tautan tersembunyi dalam entity teks, file, atau media bisa memerlukan pemeriksaan tambahan.
- Jika grup sangat aktif, uji di grup percobaan dulu. Deteksi flood bisa salah menandai pengguna aktif; sesuaikan batasnya.
- Bot API tidak menjamin bot dapat menghapus semua pesan lama; izin admin dan batasan Telegram tetap berlaku.
- Dashboard menghitung tanggal hari ini dalam UTC.
- Lakukan backup berkala untuk `antispam.sqlite3`.
