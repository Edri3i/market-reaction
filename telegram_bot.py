#!/usr/bin/env python3
"""Market Reaction (واکنش بازار) Telegram bot.

daily  : builds tidy images of today's red/orange news and sends them (06:00 Tehran).
check  : compares today's news with the last saved copy and reports what changed
         (a released result, or a revised forecast/previous), plus new Fed announcements.
Written by Ali Edrisi.
"""
import json
import os
import re
import subprocess
import sys
import uuid
import datetime
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tehran")
HIDE = {"AUD", "JPY"}
STATE_FILE = "telegram_state.json"
OUT_DIR = os.environ.get("OUT_DIR", "out")
PER_IMAGE = 6
DAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

# (pattern, persian name, lower number is better for the currency, oil inventories)
CL = [
    (r"non-?farm|nfp", "اشتغال غیرکشاورزی (NFP)", False, False),
    (r"unemployment rate", "نرخ بیکاری", True, False),
    (r"average hourly earnings|average earnings|wage price|wages", "رشد دستمزد", False, False),
    (r"core pce", "تورم هسته PCE", False, False),
    (r"core cpi", "تورم هسته مصرف‌کننده (Core CPI)", False, False),
    (r"cpi|inflation|prices? flash", "تورم مصرف‌کننده (CPI)", False, False),
    (r"ppi|producer price", "قیمت تولیدکننده (PPI)", False, False),
    (r"fomc press conference", "نشست خبری رئیس فدرال رزرو", False, False),
    (r"minutes", "صورت‌جلسه بانک مرکزی", False, False),
    (r"speaks|speech|testif|press conference|statement of", "سخنرانی مقام بانک مرکزی", False, False),
    (r"rate (statement|decision)|policy rate|bank rate|cash rate|refinancing rate|overnight rate|monetary policy|fomc|federal funds|official bank", "تصمیم نرخ بهره بانک مرکزی", False, False),
    (r"gdp", "تولید ناخالص داخلی (GDP)", False, False),
    (r"retail sales", "فروش خرده‌فروشی", False, False),
    (r"ism .*(pmi|manufacturing|services)|ism (manufacturing|services)", "شاخص مدیران خرید ISM", False, False),
    (r"pmi", "شاخص مدیران خرید (PMI)", False, False),
    (r"jolts|job openings", "فرصت‌های شغلی (JOLTS)", False, False),
    (r"adp", "اشتغال بخش خصوصی ADP", False, False),
    (r"claims", "درخواست بیمه بیکاری", True, False),
    (r"crude oil inventor|oil inventor|eia crude", "ذخایر نفت خام آمریکا", True, True),
    (r"employment change|employment$", "تغییر اشتغال", False, False),
    (r"trade balance|current account", "تراز تجاری", False, False),
    (r"confidence|sentiment|zew|ifo|tankan", "شاخص اعتماد و رضایت", False, False),
    (r"durable goods|industrial production|manufacturing production", "شاخص تولید و سفارش‌های صنعتی", False, False),
]
CL = [(re.compile(p, re.I), n, i, o) for p, n, i, o in CL]

ASSETS = [
    ("XAUUSD", "طلا"), ("EURUSD", "یورو/دلار"), ("WTI", "نفت"), ("XAGUSD", "نقره"),
    ("GBPUSD", "پوند/دلار"), ("USDCHF", "دلار/فرانک"), ("USDCAD", "دلار/دلار کانادا"),
    ("NZDUSD", "دلار نیوزیلند"), ("BTCUSD", "بیت‌کوین"),
]
SENS = {
    "USD": {"EURUSD": -.8, "GBPUSD": -.7, "USDCHF": .7, "USDCAD": .6, "NZDUSD": -.7, "XAUUSD": -.8, "XAGUSD": -.7, "WTI": -.3, "BTCUSD": -.4},
    "EUR": {"EURUSD": .9, "GBPUSD": .2, "USDCHF": -.4, "USDCAD": -.1, "NZDUSD": .1, "XAUUSD": .3, "XAGUSD": .2, "WTI": .1, "BTCUSD": .1},
    "GBP": {"EURUSD": .2, "GBPUSD": .9, "USDCHF": -.2, "USDCAD": -.1, "NZDUSD": .1, "XAUUSD": .3, "XAGUSD": .2, "WTI": .1, "BTCUSD": .1},
    "CHF": {"EURUSD": -.2, "GBPUSD": 0, "USDCHF": -.9, "USDCAD": -.1, "NZDUSD": 0, "XAUUSD": .2, "XAGUSD": .1, "WTI": 0, "BTCUSD": 0},
    "CAD": {"EURUSD": .1, "GBPUSD": .1, "USDCHF": -.1, "USDCAD": -.9, "NZDUSD": .1, "XAUUSD": .1, "XAGUSD": .1, "WTI": .4, "BTCUSD": .1},
    "NZD": {"EURUSD": .1, "GBPUSD": .1, "USDCHF": -.1, "USDCAD": -.1, "NZDUSD": .9, "XAUUSD": .1, "XAGUSD": .1, "WTI": 0, "BTCUSD": .1},
    "CNY": {"EURUSD": .1, "GBPUSD": .1, "USDCHF": 0, "USDCAD": -.1, "NZDUSD": .3, "XAUUSD": .2, "XAGUSD": .3, "WTI": .3, "BTCUSD": .1},
}
OIL = {"EURUSD": 0, "GBPUSD": 0, "USDCHF": 0, "USDCAD": -.2, "NZDUSD": 0, "XAUUSD": 0, "XAGUSD": 0, "WTI": .9, "BTCUSD": 0}


# ---------------------------------------------------------------- helpers
def classify(title):
    for rx, fa, inv, oil in CL:
        if rx.search(title):
            return fa, inv, oil
    return title, False, False


def pnum(s):
    if s is None or s == "":
        return None
    m = re.search(r"-?\d+(\.\d+)?", str(s).replace(",", ""))
    if not m:
        return None
    mult = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(str(s)[-1:].upper(), 1)
    return float(m.group(0)) * mult


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def compare(new, base):
    """+1 if new is higher than base, -1 lower, 0 equal, None unknown."""
    a, b = pnum(new), pnum(base)
    if a is None or b is None:
        return None
    return (a > b) - (a < b)


def asset_dirs(cur, inv, oil, direction):
    """direction: +1 / -1 for the number. Returns list of (name, -1|0|1)."""
    better = direction * (-1 if inv else 1)
    sens = OIL if oil else SENS.get(cur, SENS["USD"])
    out = []
    for key, fa in ASSETS:
        s = sens.get(key, 0)
        if abs(s) < 0.15:
            out.append((fa, 0))
        else:
            out.append((fa, 1 if s * better > 0 else -1))
    return out


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def today_events(data, today):
    rows = (data.get("thisweek") or []) + (data.get("nextweek") or [])
    evs = []
    for r in rows:
        try:
            if r.get("impact") not in ("High", "Medium"):
                continue
            cur = str(r.get("country", "")).upper()
            if cur in HIDE:
                continue
            ts = datetime.datetime.fromisoformat(r["date"]).astimezone(TZ)
            if ts.date() != today:
                continue
            title = r.get("title", "")
            fa, inv, oil = classify(title)
            evs.append({
                "key": r["date"] + "|" + cur + "|" + title,
                "ts": ts, "cur": cur, "impact": r.get("impact"),
                "title": title, "fa": fa, "inv": inv, "oil": oil,
                "fc": r.get("forecast") or "", "pv": r.get("previous") or "",
                "act": r.get("actual") or "",
            })
        except Exception:
            continue
    evs.sort(key=lambda e: e["ts"])
    return evs


def fresh_news(data):
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    out = []
    for n in data.get("news") or []:
        try:
            t = datetime.datetime.fromisoformat(n["ts"].replace("Z", "+00:00"))
            if 0 <= (utc_now - t).total_seconds() < 24 * 3600:
                out.append(n)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- image
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#E6F0EF;font-family:'Vazirmatn','DejaVu Sans','Noto Sans Arabic',sans-serif;color:#10302B}
.wrap{width:1000px;padding:28px}
.head{background:#16594A;color:#EAF6F5;border-radius:24px;padding:26px 32px;display:flex;justify-content:space-between;align-items:center;gap:20px}
.head h1{margin:0;font-size:44px;font-weight:800;line-height:1.3}
.head .sub{font-size:22px;color:#A9D3CF;margin-top:4px}
.head .by{direction:ltr;font-size:16px;letter-spacing:.08em;color:#A9D3CF;text-align:left}
.head .kind{display:inline-block;margin-top:10px;background:#F98F45;color:#3A1A06;border-radius:999px;padding:2px 16px;font-size:20px;font-weight:700}
.card{background:#fff;border-radius:22px;padding:24px 28px;margin-top:20px;border:2px solid #CBE0DE}
.top{display:flex;align-items:center;gap:14px}
.time{direction:ltr;font-size:38px;font-weight:800}
.cur{direction:ltr;background:#E4F0EF;border-radius:10px;padding:2px 14px;font-size:22px;font-weight:800}
.imp{border-radius:999px;padding:2px 16px;font-size:20px;font-weight:700;color:#fff}
.imp.High{background:#C4421A}.imp.Medium{background:#F98F45;color:#3A1A06}
h2{margin:12px 0 0;font-size:32px;font-weight:800;line-height:1.5}
.en{direction:ltr;text-align:right;color:#4A6A65;font-size:19px;margin-top:2px}
.nums{display:flex;gap:14px;margin-top:16px}
.box{flex:1;background:#F0F6F5;border:1px solid #CBE0DE;border-radius:14px;padding:10px 16px}
.box small{display:block;color:#4A6A65;font-size:17px}
.box b{direction:ltr;display:block;text-align:right;font-size:28px}
.box.hl{background:#16594A;border-color:#16594A;color:#EAF6F5}
.box.hl small{color:#A9D3CF}
.line{margin-top:14px;font-size:22px;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.chip{background:#EEF5F4;border-radius:999px;padding:6px 18px;font-size:21px;font-weight:600}
.up{color:#0D7F7C;font-weight:800}.down{color:#C4421A;font-weight:800}.flat{color:#4A6A65}
.note{margin-top:14px;font-size:20px;color:#4A6A65}
.foot{margin-top:22px;text-align:center;color:#4A6A65;font-size:17px}
.news{margin-top:6px;padding-top:12px;border-top:1px solid #CBE0DE;direction:ltr;text-align:left;font-size:20px;font-weight:600}
"""


def chips_html(dirs):
    parts = []
    for name, d in dirs:
        arrow = '<span class="up">▲</span>' if d > 0 else ('<span class="down">▼</span>' if d < 0 else '<span class="flat">—</span>')
        parts.append('<span class="chip">' + esc(name) + " " + arrow + "</span>")
    return '<div class="chips">' + "".join(parts) + "</div>"


def direction_word(d, a, b):
    if d is None:
        return ""
    if d == 0:
        return a + " برابر " + b + " است"
    return a + (" بالاتر از " if d > 0 else " پایین‌تر از ") + b + " است"


def card_html(e, kind, old=None):
    nums = [("پیش‌بینی", e["fc"] or "-", False), ("قبلی", e["pv"] or "-", False)]
    body = ""
    if kind == "result":
        nums = [("نتیجه اعلام‌شده", e["act"], True), ("پیش‌بینی بود", e["fc"] or "-", False), ("قبلی", e["pv"] or "-", False)]
        d = compare(e["act"], e["fc"])
        line = direction_word(d, "نتیجه", "پیش‌بینی") if d is not None else "نتیجه اعلام شد"
        body = '<div class="line">' + esc(line) + "</div>"
        if d:
            body += chips_html(asset_dirs(e["cur"], e["inv"], e["oil"], d))
            body += '<div class="note">جهت‌ها بر پایه فاصله نتیجه با پیش‌بینی، برآورد تقریبی ساعت اول.</div>'
        elif d == 0:
            body += '<div class="note">نتیجه مطابق پیش‌بینی است، پس واکنش بزرگی انتظار نمی‌رود.</div>'
    elif kind == "revised":
        ch = []
        if old and old.get("f") != e["fc"]:
            ch.append("پیش‌بینی از <bdi>" + esc(old.get("f") or "-") + "</bdi> به <bdi>" + esc(e["fc"] or "-") + "</bdi> تغییر کرد")
        if old and old.get("p") != e["pv"]:
            ch.append("عدد قبلی از <bdi>" + esc(old.get("p") or "-") + "</bdi> به <bdi>" + esc(e["pv"] or "-") + "</bdi> اصلاح شد")
        body = '<div class="line">' + "<br>".join(ch) + "</div>"
        d = compare(e["fc"], e["pv"])
        if d:
            body += '<div class="note">' + esc(direction_word(d, "پیش‌بینی", "قبلی")) + "</div>"
            body += chips_html(asset_dirs(e["cur"], e["inv"], e["oil"], d))
    else:
        d = compare(e["fc"], e["pv"])
        if d is None:
            body = '<div class="note">این رویداد عدد مقایسه‌ای ندارد؛ واکنش به لحن و پیام بستگی دارد.</div>'
        elif d == 0:
            body = '<div class="line">پیش‌بینی برابر قبلی است</div><div class="note">تغییر مهمی انتظار نمی‌رود.</div>'
        else:
            body = '<div class="line">' + esc(direction_word(d, "پیش‌بینی", "قبلی")) + "</div>" + chips_html(asset_dirs(e["cur"], e["inv"], e["oil"], d))
    nums_html = "".join(
        '<div class="box' + (" hl" if hl else "") + '"><small>' + esc(t) + "</small><b>" + esc(v) + "</b></div>" for t, v, hl in nums
    )
    en = '<div class="en">' + esc(e["title"]) + "</div>" if e["fa"] != e["title"] else ""
    return (
        '<div class="card"><div class="top"><span class="time">' + e["ts"].strftime("%H:%M") + '</span><span class="cur">' + esc(e["cur"]) +
        '</span><span class="imp ' + e["impact"] + '">' + ("قرمز" if e["impact"] == "High" else "نارنجی") + "</span></div>"
        "<h2>" + esc(e["fa"]) + "</h2>" + en + '<div class="nums">' + nums_html + "</div>" + body + "</div>"
    )


def news_card(news):
    items = "".join('<div class="news">' + esc(n.get("title", "")) + "</div>" for n in news[:5])
    return '<div class="card"><h2>اخبار مهم دلار خارج از تقویم</h2>' + items + '<div class="note">منبع: فدرال رزرو</div></div>'


def page_html(title, sub, cards, kind_label=""):
    kind = '<span class="kind">' + esc(kind_label) + "</span>" if kind_label else ""
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        '<link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;600;800&display=swap" rel="stylesheet">'
        "<style>" + CSS + "</style></head><body><div class=\"wrap\"><div class=\"head\"><div><h1>" + esc(title) + '</h1><div class="sub">' +
        esc(sub) + "</div>" + kind + '</div><div class="by">Written by Ali Edrisi</div></div>' + "".join(cards) +
        '<div class="foot">واکنش بازار · ساعت‌ها به وقت تهران · برآورد تقریبی و نه توصیه معاملاتی</div></div></body></html>'
    )


def render(html_text, path):
    from playwright.sync_api import sync_playwright

    def shot(p):
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1000, "height": 800}, device_scale_factor=1.5)
        pg.set_content(html_text, wait_until="networkidle")
        pg.evaluate("document.fonts.ready.then(() => 1)")
        pg.screenshot(path=path, full_page=True)
        b.close()

    with sync_playwright() as p:
        try:
            shot(p)
        except Exception as ex:
            if "xecutable" not in str(ex) and "install" not in str(ex):
                raise
            print("installing browser...")
            subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=True)
            shot(p)


# ---------------------------------------------------------------- telegram
def tg_ready():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def tg_call(method, fields, files=None):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    boundary = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += ("--" + boundary + '\r\nContent-Disposition: form-data; name="' + k + '"\r\n\r\n' + str(v) + "\r\n").encode("utf-8")
    for k, (fname, content) in (files or {}).items():
        body += ("--" + boundary + '\r\nContent-Disposition: form-data; name="' + k + '"; filename="' + fname + '"\r\nContent-Type: image/png\r\n\r\n').encode("utf-8")
        body += content + b"\r\n"
    body += ("--" + boundary + "--\r\n").encode("utf-8")
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/" + method, data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
    )
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as ex:
        print("telegram error", ex.code, ex.read().decode("utf-8", "replace")[:300])
        sys.exit(1)


def send_text(text):
    if not tg_ready():
        print("---- text (no token, not sent) ----\n" + text)
        return
    for i in range(0, len(text), 3800):
        tg_call("sendMessage", {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text[i:i + 3800], "disable_web_page_preview": "true"})


def send_image(path, caption=""):
    if not tg_ready():
        print("---- image saved, not sent:", path)
        return
    with open(path, "rb") as f:
        content = f.read()
    tg_call("sendPhoto", {"chat_id": os.environ["TELEGRAM_CHAT_ID"], "caption": caption[:1000]}, {"photo": (os.path.basename(path), content)})


def text_fallback(title, evs, kind, olds):
    lines = [title]
    for e in evs:
        mark = "🔴" if e["impact"] == "High" else "🟠"
        row = mark + " " + e["ts"].strftime("%H:%M") + " | " + e["cur"] + "\n" + e["fa"]
        if kind(e) == "result":
            row += "\nنتیجه: " + e["act"] + " | پیش‌بینی: " + (e["fc"] or "-") + " | قبلی: " + (e["pv"] or "-")
        else:
            row += "\nپیش‌بینی: " + (e["fc"] or "-") + " | قبلی: " + (e["pv"] or "-")
        lines.append(row)
    return "\n\n".join(lines)


def send_cards(title, sub, items, caption, kind_label=""):
    """items: list of ('event', e, kind, old) or ('news', list)"""
    os.makedirs(OUT_DIR, exist_ok=True)
    pages = []
    cur = []
    for it in items:
        if it[0] == "news":
            cur.append(news_card(it[1]))
        else:
            cur.append(card_html(it[1], it[2], it[3]))
        if len(cur) >= PER_IMAGE:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    try:
        for i, cards in enumerate(pages, 1):
            suffix = " (" + str(i) + "/" + str(len(pages)) + ")" if len(pages) > 1 else ""
            path = os.path.join(OUT_DIR, "news_" + str(i) + ".png")
            render(page_html(title, sub, cards, kind_label), path)
            send_image(path, (caption if i == 1 else "") + suffix)
    except Exception as ex:
        print("image failed, sending text instead:", repr(ex)[:300])
        evs = [it[1] for it in items if it[0] == "event"]
        kinds = {it[1]["key"]: it[2] for it in items if it[0] == "event"}
        send_text(text_fallback(caption, evs, lambda e: kinds.get(e["key"]), None))


# ---------------------------------------------------------------- modes
def baseline(evs, news):
    return {
        "ev": {e["key"]: {"f": e["fc"], "p": e["pv"], "a": e["act"]} for e in evs},
        "news": [n.get("link", "") for n in news],
    }


def mode_daily(data, today, manual):
    evs = today_events(data, today)
    news = fresh_news(data)
    state = baseline(evs, news)
    state["day"] = today.isoformat()
    if not evs and not news:
        if manual:
            send_text("امروز خبر قرمز یا نارنجی ثبت نشده است.")
        else:
            print("nothing to send today")
        return state
    red = sum(1 for e in evs if e["impact"] == "High")
    title = "اخبار مهم امروز"
    sub = DAYS[today.weekday()] + " " + today.isoformat() + " | " + str(red) + " قرمز، " + str(len(evs) - red) + " نارنجی"
    items = [("event", e, "result" if e["act"] else "daily", None) for e in evs]
    if news:
        items.append(("news", news))
    caption = title + "، " + sub
    try:
        upd = datetime.datetime.fromisoformat(data["updated"].replace("Z", "+00:00"))
        if (datetime.datetime.now(datetime.timezone.utc) - upd).total_seconds() > 12 * 3600:
            caption += "\nداده تقویم آخرین بار " + upd.astimezone(TZ).strftime("%Y-%m-%d %H:%M") + " به‌روز شده است."
    except Exception:
        pass
    send_cards(title, sub, items, caption)
    return state


def mode_check(data, today, state):
    if state.get("day") != today.isoformat():
        print("no baseline for today yet; nothing to compare")
        return state
    old = state.setdefault("ev", {})
    seen = set(state.get("news", []))
    evs = today_events(data, today)
    changed = []
    for e in evs:
        o = old.get(e["key"])
        if o is None:
            old[e["key"]] = {"f": e["fc"], "p": e["pv"], "a": e["act"]}
            continue
        if e["act"] and not o.get("a"):
            changed.append(("event", e, "result", o))
        elif e["fc"] != o.get("f") or e["pv"] != o.get("p"):
            changed.append(("event", e, "revised", o))
        old[e["key"]] = {"f": e["fc"], "p": e["pv"], "a": e["act"]}
    new_news = [n for n in fresh_news(data) if n.get("link") not in seen]
    for n in new_news:
        seen.add(n.get("link", ""))
    state["news"] = sorted(seen)
    if changed:
        parts = []
        for it in changed:
            parts.append(it[1]["fa"] + (" ← نتیجه اعلام شد" if it[2] == "result" else " ← اعداد تغییر کرد"))
        send_cards("به‌روزرسانی خبر", DAYS[today.weekday()] + " " + today.isoformat(), changed,
                   "به‌روزرسانی:\n" + "\n".join(parts), "تغییر جدید")
    if new_news:
        lines = ["📰 خبر مهم جدید دلار"]
        for n in new_news[:5]:
            lines.append("• " + n.get("title", "") + "\n" + n.get("link", ""))
        send_text("\n\n".join(lines))
    if not changed and not new_news:
        print("no changes")
    return state


def main():
    event = os.environ.get("EVENT_NAME", "workflow_dispatch")
    mode = os.environ.get("INPUT_MODE") or ("daily" if event != "workflow_run" else "check")
    if event == "schedule":
        mode = "daily"
    if event == "workflow_run":
        mode = "check"
    today = datetime.datetime.now(TZ).date()
    data = load_json("calendar.json", {})
    if not data:
        print("calendar.json missing or empty")
        return
    state = load_json(STATE_FILE, {})
    if mode == "daily":
        state = mode_daily(data, today, event == "workflow_dispatch")
    else:
        state = mode_check(data, today, state)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
