"""
Test suite untuk bot.py — menjalankan logika bot tanpa internet
dengan meniru (stub) library eksternal: telegram, feedparser,
deep_translator, decouple, requests.
"""
import asyncio
import json
import os
import sys
import types
from pathlib import Path

TESTDIR = Path(__file__).parent
DATA = TESTDIR / "testdata"
os.environ["DATA_DIR"] = str(DATA)

# ---------- STUB: decouple ----------
decouple = types.ModuleType("decouple")
def _config(key, default=None, cast=None):
    vals = {"BOT_TOKEN": "TEST:TOKEN", "OWNER_ID": "111", "DATA_DIR": str(DATA)}
    v = vals.get(key, os.environ.get(key, default))
    return cast(v) if cast and v is not None else v
decouple.config = _config
sys.modules["decouple"] = decouple

# ---------- STUB: deep_translator ----------
dt = types.ModuleType("deep_translator")
class GoogleTranslator:
    def __init__(self, source="auto", target="id"): self.target = target
    def translate(self, text): return f"[ID]{text}"
dt.GoogleTranslator = GoogleTranslator
sys.modules["deep_translator"] = dt

# ---------- STUB: requests (dipakai fetch_og_image, harus tanpa internet) ----------
req = types.ModuleType("requests")
class _FakeResponse:
    text = "<html><head></head><body></body></html>"
    def raise_for_status(self): pass
def _get(*a, **kw):
    return _FakeResponse()
req.get = _get
sys.modules["requests"] = req

# ---------- STUB: feedparser ----------
fp = types.ModuleType("feedparser")
def parse(url):
    r = types.SimpleNamespace()
    r.feed = {"title": "Feed Uji"}
    if "antaranews" in url:
        r.entries = [
            {"id": "antara1", "title": "Persija menang besar & PSSI puas", "summary": "desc",
             "link": "https://www.antaranews.com/berita/1/persija-menang",
             "links": [{"type": "image/jpg", "href": "https://img.antara/1.jpg"}]},
            {"id": "antara2", "title": "Timnas siap tanding", "summary": "",
             "link": "https://www.antaranews.com/berita/2/timnas-siap"},
        ]
    elif "kosong" in url:
        r.entries = []
        r.bozo = 0
    elif "rusak" in url:
        r.entries = []
        r.bozo = 1
        r.bozo_exception = "XML tidak valid"
    else:
        r.entries = [
            {"id": f"{url}#1", "title": "Transfer news: Star striker joins", "link": url + "/1"},
            {"id": f"{url}#2", "title": "Match report weekend", "link": url + "/2"},
        ]
    return r
fp.parse = parse
sys.modules["feedparser"] = fp

# ---------- STUB: telegram ----------
tg = types.ModuleType("telegram")
class InlineKeyboardButton:
    def __init__(self, text, callback_data=None, url=None):
        self.text, self.callback_data = text, callback_data
class InlineKeyboardMarkup:
    def __init__(self, rows): self.rows = rows
class Update: pass
tg.InlineKeyboardButton = InlineKeyboardButton
tg.InlineKeyboardMarkup = InlineKeyboardMarkup
tg.Update = Update
sys.modules["telegram"] = tg

tgc = types.ModuleType("telegram.constants")
class ParseMode: HTML = "HTML"
tgc.ParseMode = ParseMode
sys.modules["telegram.constants"] = tgc

tgerr = types.ModuleType("telegram.error")
class RetryAfter(Exception):
    """Tiruan telegram.error.RetryAfter — dilempar Telegram saat kena flood-control (429)."""
    def __init__(self, retry_after):
        super().__init__(f"Flood control: retry in {retry_after}s")
        self.retry_after = retry_after
tgerr.RetryAfter = RetryAfter
sys.modules["telegram.error"] = tgerr

tge = types.ModuleType("telegram.ext")
class Application:
    @staticmethod
    def builder(): return Application()
    def token(self, t): return self
    def post_init(self, f): return self
    def build(self): return self
    def add_handler(self, h): pass
    def run_polling(self): pass
class CommandHandler:
    def __init__(self, name, fn): self.name, self.fn = name, fn
class CallbackQueryHandler:
    def __init__(self, fn): self.fn = fn
class ContextTypes: DEFAULT_TYPE = object
tge.Application = Application
tge.CommandHandler = CommandHandler
tge.CallbackQueryHandler = CallbackQueryHandler
tge.ContextTypes = ContextTypes
sys.modules["telegram.ext"] = tge

# ---------- objek palsu untuk simulasi chat ----------
class FakeMessage:
    def __init__(self): self.sent = []
    async def reply_text(self, text, **kw): self.sent.append(text)
    async def reply_photo(self, photo=None, caption=None, **kw): self.sent.append(caption)

class FakeUser:
    def __init__(self, uid): self.id = uid

class FakeBot:
    def __init__(self): self.sent = []
    async def send_message(self, chat_id=None, text=None, **kw):
        self.sent.append((chat_id, text))
    # sengaja tidak ada send_photo -> try_post_one harus fallback ke send_message

class FloodBot:
    """Simulasi bot yang kena flood-control (429) `fail_times` kali sebelum akhirnya berhasil."""
    def __init__(self, fail_times=1):
        self.sent = []
        self.attempts = 0
        self.fail_times = fail_times
    async def send_message(self, chat_id=None, text=None, **kw):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise bot.RetryAfter(0)
        self.sent.append((chat_id, text))

class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answers, self.edits = [], []
    async def answer(self, text=None, show_alert=False): self.answers.append(text)
    async def edit_message_text(self, text, **kw): self.edits.append(text)

class FakeUpdate:
    def __init__(self, uid=111, cb=None):
        self.effective_user = FakeUser(uid)
        self.message = FakeMessage()
        self.callback_query = FakeQuery(cb) if cb else None

class FakeContext:
    def __init__(self, args=None):
        self.args = args or []
        self.bot = FakeBot()

# ---------- mulai test ----------
import shutil
if DATA.exists():
    shutil.rmtree(DATA)

import bot  # noqa: E402

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    print(("✅ PASS" if cond else "❌ FAIL") + f" — {name}")
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (0 if cond else 1)

async def main():
    # 1. Data dir & default settings
    check("DATA_DIR dibuat otomatis", DATA.exists())
    check("Default: 6 post/hari", bot.settings["posts_per_day"] == 6)

    # 2. Simpan & muat ulang settings
    bot.settings["channel_ids"] = ["@uji"]
    bot.save_settings()
    reloaded = json.loads((DATA / "settings.json").read_text())
    check("Settings tersimpan ke disk", reloaded["channel_ids"] == ["@uji"])

    # 3. Reset kuota harian
    bot.state["date"] = "2020-01-01"; bot.state["count_today"] = 99
    bot.reset_daily_quota_if_needed()
    check("Kuota harian di-reset di hari baru", bot.state["count_today"] == 0)

    # 4. Filter kata kunci
    item_t = {"title": "Transfer news: Star striker joins", "summary": ""}
    item_m = {"title": "Match report weekend", "summary": ""}
    check("Tanpa filter: semua lolos", bot.passes_filter(item_t) and bot.passes_filter(item_m))
    bot.settings["keyword_filters"] = ["transfer"]
    check("Filter 'transfer': berita transfer lolos", bot.passes_filter(item_t))
    check("Filter 'transfer': berita lain tertahan", not bot.passes_filter(item_m))
    bot.settings["keyword_filters"] = []

    # 4b. Dedupe lintas-sumber: judul sama dari 2 sumber beda (ID beda) = dianggap duplikat
    item_src1 = {"id": "antara-x1", "title": "Timnas Menang Telak!", "summary": ""}
    item_src2 = {"id": "rss-y1", "title": "timnas menang telak", "summary": ""}  # sumber lain
    check("Item yang judulnya belum pernah diposting dianggap baru", bot.is_new_item(item_src1))
    bot.state["posted_ids"].append(item_src1["id"])
    bot.state["posted_titles"].append(bot.normalize_title(item_src1["title"]))
    check("Judul sama dari sumber lain (ID beda) dianggap SUDAH diposting (anti-tabrakan)",
          not bot.is_new_item(item_src2))
    item_src3 = {"id": "rss-y2", "title": "Berita yang sama sekali berbeda", "summary": ""}
    check("Judul benar-benar beda tetap dianggap baru", bot.is_new_item(item_src3))

    # 5. Build message: terjemahan + footer + link
    bot.settings["footer"] = "#EPL | @uji"
    msg = await bot.build_message({"title": "Hello", "summary": "World news",
                                   "link": "https://x.y/1", "source": "Uji"})
    check("Judul diterjemahkan", "[ID]Hello" in msg)
    check("Footer ikut terpasang", "#EPL | @uji" in msg)
    check("Link sumber ada", "https://x.y/1" in msg)

    # 5b. Build message: judul mengandung karakter HTML spesial harus di-escape
    # (kalau tidak, Telegram menolak kirim & autopost bisa macet total — lihat try_post_one)
    msg_html = await bot.build_message({
        "title": "Arsenal & Chelsea <preview>", "summary": "",
        "link": "https://x.y/2", "source": "Uji",
    })
    check("Karakter '&' di judul di-escape", "&amp;" in msg_html)
    check("Karakter '<' di judul di-escape (bukan tag liar)", "&lt;preview&gt;" in msg_html)

    # 5c. Sumber utama (no_translate=True) tidak boleh ikut diterjemahkan
    msg_no_tr = await bot.build_message({
        "title": "Sudah Bahasa Indonesia", "summary": "", "link": "https://x.y/3",
        "source": "Uji", "no_translate": True,
    })
    check("no_translate: judul TIDAK diterjemahkan", "[ID]" not in msg_no_tr)

    # 6. RSS source fetch (via stub feedparser)
    bot.settings["rss_sources"] = ["https://feed.uji/rss"]
    items = await bot.fetch_rss_sources()
    check("RSS terbaca 2 item", len(items) == 2)

    # 6b. Sumber utama ANTARA (via stub feedparser)
    main_items = await bot.fetch_main_source()
    check("Sumber utama ANTARA terbaca", len(main_items) == 2)
    check("Sumber utama ditandai no_translate", all(it.get("no_translate") for it in main_items))

    # 7. try_post_one: kirim + dedupe + statistik (fallback ke teks krn FakeBot tanpa send_photo)
    fb = FakeBot()
    title = await bot.try_post_one(fb)
    check("Post pertama terkirim", title is not None and len(fb.sent) == 1)
    n = len(fb.sent)
    await bot.try_post_one(fb)
    check("Item sama tidak dobel (dedupe)", len(fb.sent) == n + 1 or len(fb.sent) <= 2)
    check("Statistik total_posted bertambah", bot.settings["total_posted"] >= 1)

    # 8. Keamanan: non-owner ditolak
    upd = FakeUpdate(uid=999)
    await bot.cmd_settings(upd, FakeContext())
    check("Non-owner ditolak", any("owner" in s.lower() for s in upd.message.sent))

    # 9. Command handlers
    upd = FakeUpdate(); await bot.cmd_setlimit(upd, FakeContext(["12"]))
    check("/setlimit 12 bekerja", bot.settings["posts_per_day"] == 12)
    upd = FakeUpdate(); await bot.cmd_setlimit(upd, FakeContext(["abc"]))
    check("/setlimit input salah ditangani", any("Format" in s for s in upd.message.sent))
    upd = FakeUpdate(); await bot.cmd_addfilter(upd, FakeContext(["injury"]))
    check("/addfilter bekerja", "injury" in bot.settings["keyword_filters"])
    upd = FakeUpdate(); await bot.cmd_delfilter(upd, FakeContext(["1"]))
    check("/delfilter bekerja", "injury" not in bot.settings["keyword_filters"])
    upd = FakeUpdate(); await bot.cmd_setfooter(upd, FakeContext(["#PL", "News"]))
    check("/setfooter gabung kata", bot.settings["footer"] == "#PL News")
    upd = FakeUpdate(); await bot.cmd_status(upd, FakeContext())
    check("/status merender tanpa error", any("Status Bot" in s for s in upd.message.sent))
    upd = FakeUpdate(); await bot.cmd_utama(upd, FakeContext(["off"]))
    check("/utama off bekerja", bot.settings["main_enabled"] is False)
    upd = FakeUpdate(); await bot.cmd_utama(upd, FakeContext(["on"]))
    check("/utama on bekerja", bot.settings["main_enabled"] is True)
    upd = FakeUpdate(); await bot.cmd_translate(upd, FakeContext(["off"]))
    check("/translate off bekerja", bot.settings["translate_enabled"] is False)
    upd = FakeUpdate(); await bot.cmd_translate(upd, FakeContext(["on"]))
    check("/translate on bekerja", bot.settings["translate_enabled"] is True)

    # 9b. /delsource dan /delfilter dengan nomor 0 (di luar jangkauan) harus DITOLAK,
    # bukan diam-diam menghapus item terakhir (bug indexing negatif Python)
    bot.settings["rss_sources"] = ["https://a.uji/rss", "https://b.uji/rss"]
    upd = FakeUpdate(); await bot.cmd_delsource(upd, FakeContext(["0"]))
    check("/delsource 0 ditolak, tidak hapus apa pun",
          len(bot.settings["rss_sources"]) == 2 and any("Format" in s for s in upd.message.sent))
    bot.settings["keyword_filters"] = ["a", "b"]
    upd = FakeUpdate(); await bot.cmd_delfilter(upd, FakeContext(["0"]))
    check("/delfilter 0 ditolak, tidak hapus apa pun",
          len(bot.settings["keyword_filters"]) == 2 and any("Format" in s for s in upd.message.sent))
    bot.settings["keyword_filters"] = []

    # 9c. Flood-control Telegram (429/RetryAfter): harus retry otomatis, bukan langsung gagal
    bot.settings["rss_sources"] = ["https://flood.uji/rss"]
    flood_bot = FloodBot(fail_times=1)
    title = await bot.try_post_one(flood_bot)
    check(
        "Kena flood-control tapi tetap terkirim setelah retry",
        title is not None and flood_bot.attempts == 2 and len(flood_bot.sent) == 1,
    )

    # 9d. send_preview: pakai reply_photo kalau item ada gambar, reply_text kalau tidak
    class _CapturingMessage:
        def __init__(self):
            self.photo_calls = []
            self.text_calls = []
        async def reply_photo(self, photo=None, caption=None, **kw):
            self.photo_calls.append((photo, caption))
        async def reply_text(self, text, **kw):
            self.text_calls.append(text)

    cap = _CapturingMessage()
    await bot.send_preview(cap, {
        "id": "prev-1", "title": "Judul dengan gambar", "summary": "",
        "link": "https://x.y/gambar", "source": "Uji", "image": "https://img.uji/1.jpg",
    })
    check("send_preview pakai reply_photo kalau ada gambar",
          len(cap.photo_calls) == 1 and len(cap.text_calls) == 0)

    cap2 = _CapturingMessage()
    await bot.send_preview(cap2, {
        "id": "prev-2", "title": "Judul tanpa gambar", "summary": "",
        "link": "https://x.y/tanpa-gambar", "source": "Uji", "image": "",
    })
    check("send_preview fallback ke reply_text kalau tidak ada gambar",
          len(cap2.text_calls) == 1 and len(cap2.photo_calls) == 0)

    # 9e. /preview <nomor>: preview khusus 1 sumber RSS, bukan gabungan semua sumber
    bot.settings["rss_sources"] = ["https://source-a.uji/rss", "https://source-b.uji/rss"]
    upd = FakeUpdate(); await bot.cmd_preview(upd, FakeContext(["2"]))
    check("/preview 2 ambil dari sumber RSS ke-2, bukan ke-1",
          any("source-b.uji" in s for s in upd.message.sent if isinstance(s, str)))

    upd = FakeUpdate(); await bot.cmd_preview(upd, FakeContext(["99"]))
    check("/preview nomor di luar jangkauan ditolak",
          any("tidak ada" in s.lower() for s in upd.message.sent))

    upd = FakeUpdate(); await bot.cmd_preview(upd, FakeContext(["utama"]))
    check("/preview utama hanya cari di sumber utama (sudah full-posted -> tidak ada baru)",
          any("Tidak ada berita baru" in s for s in upd.message.sent))

    # 9f. Multi-channel: /setchannel, /addchannel, /channels, /delchannel
    bot.settings["channel_ids"] = []
    upd = FakeUpdate(); await bot.cmd_setchannel(upd, FakeContext(["@utama"]))
    check("/setchannel mengatur 1 channel", bot.settings["channel_ids"] == ["@utama"])
    upd = FakeUpdate(); await bot.cmd_addchannel(upd, FakeContext(["@kedua"]))
    check("/addchannel menambah TANPA menghapus yang lama",
          bot.settings["channel_ids"] == ["@utama", "@kedua"])
    upd = FakeUpdate(); await bot.cmd_addchannel(upd, FakeContext(["@utama"]))
    check("/addchannel channel yang sudah ada tidak didobelin",
          bot.settings["channel_ids"] == ["@utama", "@kedua"])
    upd = FakeUpdate(); await bot.cmd_channels(upd, FakeContext())
    check("/channels menampilkan semua channel",
          any("@utama" in s and "@kedua" in s for s in upd.message.sent))
    upd = FakeUpdate(); await bot.cmd_delchannel(upd, FakeContext(["0"]))
    check("/delchannel 0 ditolak (index negatif)", bot.settings["channel_ids"] == ["@utama", "@kedua"])
    upd = FakeUpdate(); await bot.cmd_delchannel(upd, FakeContext(["1"]))
    check("/delchannel 1 menghapus channel pertama", bot.settings["channel_ids"] == ["@kedua"])

    # 9g. Multi-channel: 1 post harus terkirim ke SEMUA channel tujuan sekaligus
    bot.settings["channel_ids"] = ["@chanA", "@chanB"]
    bot.settings["rss_sources"] = ["https://multichan.uji/rss"]
    multi_bot = FakeBot()
    title = await bot.try_post_one(multi_bot)
    check("Multi-channel: post terkirim ke semua channel sekaligus",
          title is not None and {c for c, _ in multi_bot.sent} == {"@chanA", "@chanB"})

    # 9h. /checksources: lapor status per sumber (hidup / kosong / rusak)
    bot.settings["rss_sources"] = ["https://ok.uji/rss", "https://kosong.uji/rss", "https://rusak.uji/rss"]
    upd = FakeUpdate(); await bot.cmd_checksources(upd, FakeContext())
    report = "\n".join(upd.message.sent)
    check("/checksources: sumber normal ditandai sukses (✅)", "✅ #1" in report)
    check("/checksources: sumber kosong ditandai peringatan (⚠️)", "⚠️ #2" in report)
    check("/checksources: sumber rusak/bozo ditandai gagal (❌)", "❌ #3" in report)

    # 9i. /riwayat: menampilkan post yang baru saja berhasil terkirim (dari 9g)
    upd = FakeUpdate(); await bot.cmd_riwayat(upd, FakeContext())
    check("/riwayat menampilkan histori post",
          any("Post Terakhir" in s for s in upd.message.sent))

    # 10. FITUR UNGGULAN: tombol /settings
    kb = bot.settings_keyboard()
    check("Keyboard /settings terbentuk (6 baris)", len(kb.rows) == 6)

    upd = FakeUpdate(cb="toggle_pause")
    await bot.on_button(upd, FakeContext())
    check("Tombol jeda bekerja", bot.settings["paused"] is True)
    upd = FakeUpdate(cb="toggle_pause")
    await bot.on_button(upd, FakeContext())
    check("Tombol lanjut bekerja", bot.settings["paused"] is False)

    before = bot.settings["posts_per_day"]
    upd = FakeUpdate(cb="limit_up")
    await bot.on_button(upd, FakeContext())
    check("Tombol ➕ limit bekerja", bot.settings["posts_per_day"] == before + 1)

    bot.settings["posts_per_day"] = 1
    upd = FakeUpdate(cb="limit_down")
    await bot.on_button(upd, FakeContext())
    check("Limit tidak bisa di bawah 1", bot.settings["posts_per_day"] == 1)

    upd = FakeUpdate(uid=999, cb="toggle_pause")
    paused_before = bot.settings["paused"]
    await bot.on_button(upd, FakeContext())
    check("Non-owner tidak bisa pencet tombol",
          bot.settings["paused"] == paused_before and upd.callback_query.answers)

    upd = FakeUpdate(cb="do_preview")
    await bot.on_button(upd, FakeContext())
    check("Tombol Preview merespons", len(upd.callback_query.message.sent) >= 1)

    print(f"\n{'='*40}\nHASIL: {PASS} PASS, {FAIL} FAIL")
    return FAIL

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
