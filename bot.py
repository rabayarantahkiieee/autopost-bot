# ============================================================
# PL News AutoPost Bot — Versi Interaktif
#
# Semua pengaturan bisa lewat chat ke bot (khusus owner):
#   /sources             -> lihat daftar sumber
#   /addsource <url>     -> tambah sumber RSS (mis. bridge Nitter)
#   /delsource <nomor>   -> hapus sumber
#   /plnews on|off       -> nyalakan/matikan sumber premierleague.com
#   /setchannel <id>     -> atur channel tujuan
#   /setlimit <angka>    -> maksimal posting per hari
#   /setinterval <menit> -> jeda pengecekan berita
#   /pause  /resume      -> jeda / lanjutkan posting
#   /status              -> lihat semua pengaturan & statistik
#   /testpost            -> kirim 1 post percobaan sekarang
#
# File .env cukup berisi BOT_TOKEN dan OWNER_ID.
# Pengaturan lain disimpan otomatis di settings.json.
# ============================================================

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup
from decouple import config
from deep_translator import GoogleTranslator
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO, format="[%(levelname)s] %(asctime)s - %(message)s"
)
log = logging.getLogger("PLNewsBot")

BOT_TOKEN = config("BOT_TOKEN")
OWNER_ID = config("OWNER_ID", cast=int)   # ID Telegram kamu (dapat dari @userinfobot)

# Folder penyimpanan data. Untuk Sevalla: mount persistent disk di /data
# lalu set env var DATA_DIR=/data supaya pengaturan tidak hilang saat redeploy.
DATA_DIR = Path(config("DATA_DIR", default="."))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"
STATE_FILE = DATA_DIR / "posted.json"
MAX_SUMMARY_CHARS = 400

PL_API = "https://footballapi.pulselive.com/content/PremierLeague/text/EN/"
PL_HEADERS = {
    "Origin": "https://www.premierleague.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}

DEFAULT_SETTINGS = {
    "channel_id": "",          # diisi lewat /setchannel
    "posts_per_day": 6,
    "check_interval_min": 10,
    "target_lang": "id",
    "pl_news_enabled": True,   # sumber premierleague.com
    "rss_sources": [],         # daftar URL RSS tambahan (mis. Nitter)
    "paused": False,
    "keyword_filters": [],     # kalau diisi, hanya berita yang mengandung kata ini yang diposting
    "footer": "",              # teks tambahan di akhir tiap post (mis. hashtag / nama channel)
    "total_posted": 0,         # statistik total post sepanjang masa
}


# ---------------- PENYIMPANAN ----------------
def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


settings = {**DEFAULT_SETTINGS, **load_json(SETTINGS_FILE, {})}
state = load_json(STATE_FILE, {"posted_ids": [], "date": "", "count_today": 0})


def save_settings():
    save_json(SETTINGS_FILE, settings)


def save_state():
    state["posted_ids"] = state["posted_ids"][-500:]
    save_json(STATE_FILE, state)


def reset_daily_quota_if_needed():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("date") != today:
        state["date"] = today
        state["count_today"] = 0


# ---------------- UTIL ----------------
def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or update.effective_user.id != OWNER_ID:
            if update.message:
                await update.message.reply_text("⛔ Maaf, cuma owner yang bisa pakai perintah ini.")
            return
        return await func(update, context)
    return wrapper


def clean_html(raw: str) -> str:
    text = BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def translate(text: str) -> str:
    if not text:
        return text
    try:
        return GoogleTranslator(source="auto", target=settings["target_lang"]).translate(text[:4500])
    except Exception as exc:
        log.warning("Translate gagal (%s), pakai teks asli.", exc)
        return text


# ---------------- SUMBER BERITA ----------------
def fetch_pl_news(limit: int = 10) -> list[dict]:
    if not settings["pl_news_enabled"]:
        return []
    items = []
    try:
        r = requests.get(
            PL_API, params={"pageSize": limit, "page": 0},
            headers=PL_HEADERS, timeout=20,
        )
        r.raise_for_status()
        for c in r.json().get("content", []):
            title = clean_html(c.get("title", ""))
            if not title:
                continue
            items.append({
                "id": f"pl-{c.get('id')}",
                "title": title,
                "summary": clean_html(c.get("summary") or c.get("description") or ""),
                "link": f"https://www.premierleague.com/news/{c.get('id')}",
                "source": "Premier League",
            })
    except Exception as exc:
        log.warning("API PL gagal (%s), coba scrape HTML...", exc)
        items = fetch_pl_news_html(limit)
    return items


def fetch_pl_news_html(limit: int = 10) -> list[dict]:
    items = []
    try:
        r = requests.get("https://www.premierleague.com/en/news",
                         headers=PL_HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href*='/news/']"):
            href = a.get("href", "")
            title = clean_html(a.get_text())
            if not title or len(title) < 15:
                continue
            link = href if href.startswith("http") else f"https://www.premierleague.com{href}"
            items.append({
                "id": "pl-" + re.sub(r"\W+", "-", href),
                "title": title, "summary": "",
                "link": link, "source": "Premier League",
            })
            if len(items) >= limit:
                break
    except Exception as exc:
        log.error("Scrape HTML PL gagal: %s", exc)
    return items


def fetch_rss_sources(limit_per_feed: int = 5) -> list[dict]:
    items = []
    for url in settings["rss_sources"]:
        try:
            feed = feedparser.parse(url)
            name = feed.feed.get("title", url)
            for e in feed.entries[:limit_per_feed]:
                text = clean_html(e.get("title") or e.get("summary") or "")
                if not text:
                    continue
                items.append({
                    "id": "rss-" + (e.get("id") or e.get("link", text[:50])),
                    "title": text, "summary": "",
                    "link": e.get("link", url), "source": name,
                })
        except Exception as exc:
            log.warning("Feed %s gagal: %s", url, exc)
    return items


def passes_filter(item: dict) -> bool:
    """True kalau tidak ada filter, atau judul/ringkasan mengandung salah satu kata kunci."""
    if not settings["keyword_filters"]:
        return True
    text = (item["title"] + " " + item["summary"]).lower()
    return any(k.lower() in text for k in settings["keyword_filters"])


def build_message(item: dict) -> str:
    title_id = translate(item["title"])
    summary_id = translate(item["summary"][:MAX_SUMMARY_CHARS]) if item["summary"] else ""
    parts = [f"⚽️ <b>{title_id}</b>"]
    if summary_id and summary_id.lower() != title_id.lower():
        parts.append(summary_id)
    parts.append(f'🔗 <a href="{item["link"]}">Baca selengkapnya</a> — {item["source"]}')
    if settings["footer"]:
        parts.append(settings["footer"])
    return "\n\n".join(parts)


async def try_post_one(bot) -> str | None:
    """Cari 1 berita baru dan posting. Return judul kalau sukses."""
    if not settings["channel_id"]:
        return None
    candidates = fetch_pl_news() + fetch_rss_sources()
    for item in candidates:
        if item["id"] in state["posted_ids"] or not passes_filter(item):
            continue
        try:
            await bot.send_message(
                chat_id=settings["channel_id"],
                text=build_message(item),
                parse_mode=ParseMode.HTML,
            )
            state["posted_ids"].append(item["id"])
            state["count_today"] += 1
            settings["total_posted"] = settings.get("total_posted", 0) + 1
            save_settings()
            save_state()
            return item["title"]
        except Exception as exc:
            log.error("Gagal kirim: %s", exc)
            return None
    return None


# ---------------- LOOP POSTING OTOMATIS ----------------
async def poster_loop(app: Application):
    last_post_time = 0.0
    while True:
        try:
            reset_daily_quota_if_needed()
            if (
                not settings["paused"]
                and settings["channel_id"]
                and state["count_today"] < settings["posts_per_day"]
            ):
                min_gap = 86400 / max(settings["posts_per_day"], 1)
                now = asyncio.get_event_loop().time()
                if not last_post_time or (now - last_post_time) >= min_gap:
                    title = await try_post_one(app.bot)
                    if title:
                        last_post_time = asyncio.get_event_loop().time()
                        log.info("Terposting: %s", title[:60])
        except Exception as exc:
            log.error("Error di loop: %s", exc)
        await asyncio.sleep(settings["check_interval_min"] * 60)


# ---------------- PERINTAH BOT ----------------
HELP_TEXT = (
    "🤖 <b>PL News AutoPost Bot</b>\n\n"
    "⭐️ <b>/settings — MENU TOMBOL</b>\n"
    "Cara paling gampang atur bot: jeda/lanjut, on-off sumber,\n"
    "jumlah post per hari, preview & test post — semua tinggal pencet!\n\n"
    "<b>Pengaturan sumber:</b>\n"
    "/sources — lihat daftar sumber\n"
    "/addsource &lt;url_rss&gt; — tambah sumber RSS\n"
    "/delsource &lt;nomor&gt; — hapus sumber RSS\n"
    "/plnews on|off — sumber premierleague.com\n\n"
    "<b>Pengaturan posting:</b>\n"
    "/setchannel &lt;id&gt; — channel tujuan (mis. @channelku atau -100...)\n"
    "/setlimit &lt;angka&gt; — maks posting per hari\n"
    "/setinterval &lt;menit&gt; — jeda cek berita\n"
    "/pause — hentikan sementara\n"
    "/resume — lanjutkan\n\n"
    "<b>Filter & tampilan:</b>\n"
    "/filters — lihat filter kata kunci\n"
    "/addfilter &lt;kata&gt; — hanya posting berita berisi kata ini\n"
    "/delfilter &lt;nomor&gt; — hapus filter\n"
    "/setfooter &lt;teks&gt; — teks/hashtag di akhir tiap post\n"
    "/clearfooter — hapus footer\n\n"
    "<b>Lainnya:</b>\n"
    "/status — lihat semua pengaturan & statistik\n"
    "/preview — lihat calon post berikutnya (tanpa mengirim)\n"
    "/testpost — kirim 1 post percobaan sekarang"
)


@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_status_body(update.message)


@owner_only
async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rss = "\n".join(
        f"{i+1}. {u}" for i, u in enumerate(settings["rss_sources"])
    ) or "(tidak ada)"
    pl = "✅ aktif" if settings["pl_news_enabled"] else "❌ mati"
    await update.message.reply_text(
        f"📰 Sumber berita:\n\n• premierleague.com: {pl}\n\nRSS tambahan:\n{rss}\n\n"
        "Tambah: /addsource <url>\nHapus: /delsource <nomor>"
    )


@owner_only
async def cmd_addsource(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Format: /addsource https://contoh.com/feed.rss")
        return
    url = context.args[0]
    if not url.startswith("http"):
        await update.message.reply_text("URL harus diawali http:// atau https://")
        return
    # tes dulu feed-nya kebaca atau nggak
    feed = feedparser.parse(url)
    if not feed.entries:
        await update.message.reply_text(
            "⚠️ Feed itu tidak terbaca / kosong. Tetap kusimpan, tapi cek lagi URL-nya ya."
        )
    settings["rss_sources"].append(url)
    save_settings()
    await update.message.reply_text(f"✅ Sumber ditambahkan:\n{url}")


@owner_only
async def cmd_delsource(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(context.args[0]) - 1
        removed = settings["rss_sources"].pop(idx)
        save_settings()
        await update.message.reply_text(f"🗑 Dihapus:\n{removed}")
    except (IndexError, ValueError, TypeError):
        await update.message.reply_text(
            "Format: /delsource <nomor>\nLihat nomornya di /sources"
        )


@owner_only
async def cmd_plnews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args[0].lower() if context.args else "")
    if arg not in ("on", "off"):
        await update.message.reply_text("Format: /plnews on  atau  /plnews off")
        return
    settings["pl_news_enabled"] = arg == "on"
    save_settings()
    await update.message.reply_text(
        f"Sumber premierleague.com sekarang: {'✅ aktif' if arg == 'on' else '❌ mati'}"
    )


@owner_only
async def cmd_setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Format: /setchannel @namachannel  atau  /setchannel -1001234567890\n"
            "Jangan lupa jadikan bot ini admin di channel tersebut!"
        )
        return
    settings["channel_id"] = context.args[0]
    save_settings()
    await update.message.reply_text(
        f"✅ Channel tujuan diatur ke: {settings['channel_id']}\n"
        "Coba /testpost untuk memastikan bot bisa mengirim ke sana."
    )


@owner_only
async def cmd_setlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(context.args[0])
        if not 1 <= n <= 100:
            raise ValueError
        settings["posts_per_day"] = n
        save_settings()
        await update.message.reply_text(f"✅ Maksimal posting per hari: {n}")
    except (IndexError, ValueError, TypeError):
        await update.message.reply_text("Format: /setlimit <angka 1-100>")


@owner_only
async def cmd_setinterval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(context.args[0])
        if not 1 <= n <= 1440:
            raise ValueError
        settings["check_interval_min"] = n
        save_settings()
        await update.message.reply_text(f"✅ Bot akan cek berita tiap {n} menit.")
    except (IndexError, ValueError, TypeError):
        await update.message.reply_text("Format: /setinterval <menit 1-1440>")


@owner_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings["paused"] = True
    save_settings()
    await update.message.reply_text("⏸ Posting dijeda. /resume untuk lanjut.")


@owner_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings["paused"] = False
    save_settings()
    await update.message.reply_text("▶️ Posting dilanjutkan!")


@owner_only
async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lst = "\n".join(
        f"{i+1}. {k}" for i, k in enumerate(settings["keyword_filters"])
    ) or "(tidak ada — semua berita diposting)"
    await update.message.reply_text(
        f"🔍 Filter kata kunci:\n{lst}\n\n"
        "Kalau ada filter, HANYA berita yang mengandung salah satu kata itu yang diposting.\n"
        "Tambah: /addfilter transfer\nHapus: /delfilter <nomor>"
    )


@owner_only
async def cmd_addfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Format: /addfilter <kata>\nContoh: /addfilter transfer\n"
            "Catatan: filter dicocokkan ke judul BERBAHASA INGGRIS (sebelum diterjemahkan)."
        )
        return
    kw = " ".join(context.args)
    settings["keyword_filters"].append(kw)
    save_settings()
    await update.message.reply_text(f"✅ Filter ditambahkan: “{kw}”")


@owner_only
async def cmd_delfilter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        idx = int(context.args[0]) - 1
        removed = settings["keyword_filters"].pop(idx)
        save_settings()
        await update.message.reply_text(f"🗑 Filter dihapus: “{removed}”")
    except (IndexError, ValueError, TypeError):
        await update.message.reply_text("Format: /delfilter <nomor>\nLihat nomornya di /filters")


@owner_only
async def cmd_setfooter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Format: /setfooter <teks>\nContoh: /setfooter #PremierLeague #EPL | Join @channelku"
        )
        return
    settings["footer"] = " ".join(context.args)
    save_settings()
    await update.message.reply_text(f"✅ Footer diatur:\n{settings['footer']}")


@owner_only
async def cmd_clearfooter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    settings["footer"] = ""
    save_settings()
    await update.message.reply_text("✅ Footer dihapus.")


@owner_only
async def cmd_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Mengambil calon post berikutnya...")
    candidates = fetch_pl_news() + fetch_rss_sources()
    for item in candidates:
        if item["id"] in state["posted_ids"] or not passes_filter(item):
            continue
        await update.message.reply_text(
            "👀 <b>PREVIEW</b> (tidak dikirim ke channel):\n\n" + build_message(item),
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        "Tidak ada berita baru yang lolos filter saat ini."
    )


@owner_only
async def cmd_testpost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not settings["channel_id"]:
        await update.message.reply_text("Atur channel dulu: /setchannel <id>")
        return
    await update.message.reply_text("⏳ Mencari berita untuk post percobaan...")
    reset_daily_quota_if_needed()
    title = await try_post_one(context.bot)
    if title:
        await update.message.reply_text(f"✅ Terkirim!\n\n{title[:100]}")
    else:
        await update.message.reply_text(
            "❌ Gagal — kemungkinan: tidak ada berita baru, bot belum jadi admin "
            "di channel, atau ID channel salah. Cek /status."
        )


# ---------------- FITUR UNGGULAN: MENU TOMBOL /settings ----------------
def settings_keyboard() -> InlineKeyboardMarkup:
    p = settings
    rows = [
        [InlineKeyboardButton(
            f"{'▶️ Lanjutkan Posting' if p['paused'] else '⏸ Jeda Posting'}",
            callback_data="toggle_pause")],
        [InlineKeyboardButton(
            f"Berita PL: {'✅ AKTIF' if p['pl_news_enabled'] else '❌ MATI'} (tekan utk ubah)",
            callback_data="toggle_pl")],
        [
            InlineKeyboardButton("➖", callback_data="limit_down"),
            InlineKeyboardButton(f"📮 {p['posts_per_day']} post/hari", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data="limit_up"),
        ],
        [
            InlineKeyboardButton("➖", callback_data="interval_down"),
            InlineKeyboardButton(f"⏱ cek tiap {p['check_interval_min']} mnt", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data="interval_up"),
        ],
        [
            InlineKeyboardButton("👀 Preview", callback_data="do_preview"),
            InlineKeyboardButton("🚀 Test Post", callback_data="do_testpost"),
        ],
        [InlineKeyboardButton("📊 Status Lengkap", callback_data="show_status")],
    ]
    return InlineKeyboardMarkup(rows)


def settings_text() -> str:
    return (
        "⚙️ <b>Pengaturan Cepat</b>\n\n"
        f"Channel: <code>{settings['channel_id'] or '⚠️ belum diatur — pakai /setchannel'}</code>\n"
        f"Status: {'⏸ dijeda' if settings['paused'] else '▶️ aktif'} · "
        f"Hari ini: {state['count_today']}/{settings['posts_per_day']} post\n\n"
        "Tekan tombol di bawah untuk mengubah pengaturan.\n"
        "Untuk sumber/filter/footer, ketik /help."
    )


@owner_only
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_quota_if_needed()
    await update.message.reply_text(
        settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_keyboard()
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not update.effective_user or update.effective_user.id != OWNER_ID:
        if q:
            await q.answer("⛔ Khusus owner.", show_alert=True)
        return
    action = q.data
    reset_daily_quota_if_needed()

    if action == "toggle_pause":
        settings["paused"] = not settings["paused"]
        await q.answer("Dijeda." if settings["paused"] else "Aktif lagi!")
    elif action == "toggle_pl":
        settings["pl_news_enabled"] = not settings["pl_news_enabled"]
        await q.answer("Diubah!")
    elif action == "limit_up":
        settings["posts_per_day"] = min(settings["posts_per_day"] + 1, 100)
        await q.answer(f"{settings['posts_per_day']} post/hari")
    elif action == "limit_down":
        settings["posts_per_day"] = max(settings["posts_per_day"] - 1, 1)
        await q.answer(f"{settings['posts_per_day']} post/hari")
    elif action == "interval_up":
        settings["check_interval_min"] = min(settings["check_interval_min"] + 5, 1440)
        await q.answer(f"Tiap {settings['check_interval_min']} menit")
    elif action == "interval_down":
        settings["check_interval_min"] = max(settings["check_interval_min"] - 5, 5)
        await q.answer(f"Tiap {settings['check_interval_min']} menit")
    elif action == "do_preview":
        await q.answer("Mengambil preview...")
        candidates = fetch_pl_news() + fetch_rss_sources()
        sent = False
        for item in candidates:
            if item["id"] in state["posted_ids"] or not passes_filter(item):
                continue
            await q.message.reply_text(
                "👀 <b>PREVIEW</b> (tidak dikirim ke channel):\n\n" + build_message(item),
                parse_mode=ParseMode.HTML,
            )
            sent = True
            break
        if not sent:
            await q.message.reply_text("Tidak ada berita baru yang lolos filter saat ini.")
        return
    elif action == "do_testpost":
        if not settings["channel_id"]:
            await q.answer("Atur channel dulu: /setchannel", show_alert=True)
            return
        await q.answer("Mengirim test post...")
        title = await try_post_one(context.bot)
        await q.message.reply_text(
            f"✅ Terkirim!\n\n{title[:100]}" if title
            else "❌ Gagal — cek: bot sudah admin di channel? ID channel benar? Ada berita baru?"
        )
        return
    elif action == "show_status":
        await q.answer()
        await cmd_status_body(q.message)
        return
    else:
        await q.answer()
        return

    save_settings()
    try:
        await q.edit_message_text(
            settings_text(), parse_mode=ParseMode.HTML, reply_markup=settings_keyboard()
        )
    except Exception:
        pass  # Telegram menolak edit kalau isinya tidak berubah — aman diabaikan


async def cmd_status_body(message):
    """Isi /status, dipakai command & tombol."""
    reset_daily_quota_if_needed()
    rss = "\n".join(
        f"  {i+1}. {u}" for i, u in enumerate(settings["rss_sources"])
    ) or "  (tidak ada)"
    msg = (
        "📊 <b>Status Bot</b>\n\n"
        f"Channel tujuan: <code>{settings['channel_id'] or 'belum diatur'}</code>\n"
        f"Status: {'⏸ dijeda' if settings['paused'] else '▶️ aktif'}\n"
        f"Posting hari ini: {state['count_today']}/{settings['posts_per_day']}\n"
        f"Cek berita tiap: {settings['check_interval_min']} menit\n"
        f"Bahasa terjemahan: {settings['target_lang']}\n\n"
        f"Sumber premierleague.com: {'✅ aktif' if settings['pl_news_enabled'] else '❌ mati'}\n"
        f"Sumber RSS tambahan:\n{rss}\n\n"
        f"Filter kata kunci: {', '.join(settings['keyword_filters']) or '(tidak ada — semua berita diposting)'}\n"
        f"Footer: {settings['footer'] or '(tidak ada)'}\n"
        f"Total post sepanjang masa: {settings.get('total_posted', 0)}"
    )
    await message.reply_text(msg, parse_mode=ParseMode.HTML)



async def post_init(app: Application):
    asyncio.create_task(poster_loop(app))
    log.info("Bot siap. Chat bot-mu di Telegram dan ketik /start.")


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    handlers = {
        "start": cmd_start, "help": cmd_start,
        "settings": cmd_settings,
        "status": cmd_status, "sources": cmd_sources,
        "addsource": cmd_addsource, "delsource": cmd_delsource,
        "plnews": cmd_plnews, "setchannel": cmd_setchannel,
        "setlimit": cmd_setlimit, "setinterval": cmd_setinterval,
        "pause": cmd_pause, "resume": cmd_resume,
        "testpost": cmd_testpost, "preview": cmd_preview,
        "filters": cmd_filters, "addfilter": cmd_addfilter,
        "delfilter": cmd_delfilter, "setfooter": cmd_setfooter,
        "clearfooter": cmd_clearfooter,
    }
    for name, fn in handlers.items():
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.run_polling()


if __name__ == "__main__":
    main()
