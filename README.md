# ⚽ PL News AutoPost Bot (Interaktif)

Bot Telegram yang otomatis mengambil berita dari **premierleague.com** (+ sumber RSS tambahan), menerjemahkannya ke **Bahasa Indonesia**, lalu memposting ke channel kamu. Semua pengaturan dilakukan **langsung lewat chat ke bot** — tidak perlu edit file atau restart.


## ⭐ Fitur Unggulan: Menu Tombol `/settings`

Ketik `/settings` di chat bot, dan semua pengaturan penting muncul sebagai **tombol yang tinggal dipencet** — tanpa mengetik command sama sekali:

- ⏸/▶️ Jeda & lanjutkan posting (1 tombol)
- ✅/❌ Nyalakan-matikan sumber premierleague.com
- ➖/➕ Atur jumlah post per hari
- ➖/➕ Atur interval pengecekan berita
- 👀 Preview calon post berikutnya (dikirim ke kamu, bukan ke channel)
- 🚀 Test post langsung ke channel
- 📊 Status lengkap

Tampilan menu otomatis ter-update setiap kali kamu memencet tombol. Cuma owner (OWNER_ID) yang bisa memakainya — orang lain yang memencet akan ditolak.

Bot ini juga sudah diuji dengan **28 automated test** (`test_bot.py`) yang mencakup penyimpanan setting, filter, dedupe, keamanan owner-only, dan semua tombol. Jalankan sendiri dengan `python3 test_bot.py`.

## Perintah Bot (khusus owner)

| Perintah | Fungsi |
|---|---|
| `/settings` | ⭐ Menu tombol interaktif — cara termudah atur bot |
| `/start` atau `/help` | Lihat semua perintah |
| `/status` | Lihat semua pengaturan & jumlah post hari ini |
| `/sources` | Lihat daftar sumber berita |
| `/addsource <url>` | Tambah sumber RSS baru |
| `/delsource <nomor>` | Hapus sumber RSS |
| `/plnews on/off` | Nyalakan/matikan sumber premierleague.com |
| `/setchannel <id>` | Atur channel tujuan (`@namachannel` atau `-100...`) |
| `/setlimit <angka>` | Maksimal posting per hari |
| `/setinterval <menit>` | Seberapa sering bot cek berita baru |
| `/pause` / `/resume` | Jeda / lanjutkan posting |
| `/testpost` | Kirim 1 post percobaan sekarang juga |

Pengaturan tersimpan otomatis di `settings.json`, jadi tidak hilang walau bot di-restart.

## Cara Setup

1. Buat bot di [@BotFather](https://t.me/BotFather) → simpan token.
2. Cari tahu **ID Telegram kamu sendiri** lewat [@userinfobot](https://t.me/userinfobot) (angka, misalnya `123456789`).
3. Install dependensi:
   ```bash
   pip install -r requirements.txt
   ```
4. Salin `.env.sample` jadi `.env`, isi `BOT_TOKEN` dan `OWNER_ID`.
5. Jalankan:
   ```bash
   python3 bot.py
   ```
6. Chat bot kamu di Telegram → `/start` → atur channel dengan `/setchannel` (jangan lupa jadikan bot **admin** di channel itu) → `/testpost` untuk memastikan jalan.

## Cara upload ke GitHub kamu

**Cara termudah (tanpa command line):**
1. Buka repo kamu di github.com
2. Klik **Add file → Upload files**
3. Drag semua file di folder ini (KECUALI `.env` kalau sudah kamu buat!)
4. Klik **Commit changes**

**Atau lewat git:**
```bash
git clone https://github.com/USERNAME/autopost-bot.git
cd autopost-bot
# salin semua file project ke folder ini, lalu:
git add .
git commit -m "PL news autopost bot"
git push
```

⚠️ **JANGAN PERNAH upload file `.env` ke GitHub** — di dalamnya ada token bot kamu. Siapa pun yang melihatnya bisa membajak bot-mu. File `.gitignore` di project ini sudah otomatis mencegahnya, jangan dihapus.

## Kendala yang mungkin terjadi

1. **Sumber X (Twitter) tidak stabil.** X memblokir akses baca gratis. Bridge gratis (Nitter dll.) sering mati. Kalau feed mati, bot tidak error — dia skip dan lanjut pakai sumber lain.
2. **Endpoint premierleague.com bisa berubah.** Bot punya 2 metode (API + scrape HTML) sebagai cadangan, tapi kalau situsnya dirombak total, kode perlu disesuaikan.
3. **Google Translate gratis ada batas tak resmi.** Kalau posting sangat sering (ratusan/hari), translate bisa sesekali gagal — bot otomatis pakai teks asli sebagai cadangan.
4. **Butuh hosting 24 jam.** Kalau dijalankan di laptop, bot mati saat laptop mati. Solusi: VPS murah, atau platform seperti Railway/Render (jalankan sebagai *worker*, bukan web service).
5. **Bot harus admin di channel** dengan izin kirim pesan, kalau tidak `/testpost` akan gagal.
6. **Hak cipta.** Bot ini sengaja memposting ringkasan + link, bukan artikel penuh. Jangan diubah jadi menyalin artikel penuh.

## Lisensi

Bebas dipakai dan dimodifikasi.

---

# 🚀 Deploy ke Sevalla (Docker)

Bot ini sudah dilengkapi `Dockerfile`, tinggal ikuti langkah berikut:

## 1. Push project ke GitHub
Pastikan semua file ini ada di repo kamu: `bot.py`, `requirements.txt`, `Dockerfile`, `.dockerignore`, `.gitignore`. (JANGAN push file `.env`.)

## 2. Buat aplikasi di Sevalla
1. Dashboard Sevalla → **Applications → Add application**
2. Hubungkan repo GitHub kamu (`autopost-bot`), branch `main`
3. **Build type: Dockerfile** (build path: `Dockerfile`)
4. Pilih lokasi data center (Singapore paling dekat dari Indonesia)

## 3. Ubah proses jadi Background Worker
Bot Telegram TIDAK menerima HTTP request, jadi jangan jalankan sebagai web process:
1. Buka **Processes**
2. Hapus/edit web process bawaan → buat **Background Worker**
3. Start command: `python bot.py`
4. Pilih pod size terkecil (bot ini sangat ringan)

## 4. Set environment variables
Di **Environment variables**, tambahkan:

| Nama | Nilai |
|---|---|
| `BOT_TOKEN` | token dari @BotFather |
| `OWNER_ID` | ID Telegram kamu (dari @userinfobot) |
| `DATA_DIR` | `/data` |

## 5. Tambahkan Persistent Disk (PENTING!)
Tanpa ini, semua pengaturan (`/setchannel`, sumber, filter, daftar berita yang sudah diposting) HILANG setiap redeploy, dan bot bisa memposting ulang berita lama:
1. Buka **Disks → Create disk**
2. Mount path: `/data`
3. Ukuran terkecil sudah lebih dari cukup (file datanya cuma beberapa KB)
4. Pasangkan ke background worker kamu

## 6. Deploy!
Klik Deploy, tunggu build selesai, lalu cek **Logs** — kalau muncul `Bot siap...` berarti sukses. Chat bot-mu di Telegram → `/start` → atur semuanya dari sana.

## Tes lokal pakai Docker (opsional)
```bash
docker build -t autopost-bot .
docker run --env-file .env -e DATA_DIR=/data -v botdata:/data autopost-bot
```
