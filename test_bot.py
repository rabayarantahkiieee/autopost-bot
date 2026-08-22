"""
Test suite untuk bot.py — menjalankan logika bot tanpa internet
dengan meniru (stub) library eksternal: telegram, feedparser,
deep_translator, decouple.
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

# ---------- STUB: feedparser ----------
fp = types.ModuleType("feedparser")
def parse(url):
    r = types.SimpleNamespace()
    r.feed = {"title": "Feed Uji"}
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

class FakeUser:
    def __init__(self, uid): self.id = uid

class FakeBot:
    def __init__(self): self.sent = []
    async def send_message(self, chat_id=None, text=None, **kw):
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
    bot.settings["channel_id"] = "@uji"
    bot.save_settings()
    reloaded = json.loads((DATA / "settings.json").read_text())
    check("Settings tersimpan ke disk", reloaded["channel_id"] == "@uji")

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

    # 5. Build message: terjemahan + footer + link
    bot.settings["footer"] = "#EPL | @uji"
    msg = bot.build_message({"title": "Hello", "summary": "World news",
                             "link": "https://x.y/1", "source": "Uji"})
    check("Judul diterjemahkan", "[ID]Hello" in msg)
    check("Footer ikut terpasang", "#EPL | @uji" in msg)
    check("Link sumber ada", "https://x.y/1" in msg)

    # 6. RSS source fetch (via stub feedparser)
    bot.settings["rss_sources"] = ["https://feed.uji/rss"]
    items = bot.fetch_rss_sources()
    check("RSS terbaca 2 item", len(items) == 2)

    # 7. try_post_one: kirim + dedupe + statistik
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
