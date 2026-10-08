"""Парсинг источников юзов: каналы Telegram (t.me/s/…), любые сайты, файлы."""
import os, re
from bs4 import BeautifulSoup
from generator import mutations, valid

MENTION = re.compile(r"(?:@|t\.me/|telegram\.me/)([a-zA-Z][a-zA-Z0-9_]{3,31})")
WORD = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_]{3,31}\b")
SKIP = {"joinchat", "addstickers", "share", "proxy", "socks", "iv", "s", "c", "addlist", "boost", "contact", "setlanguage"}


def extract(text, words=True):
    """Все юзы из текста: @упоминания, t.me-ссылки и (опционально) просто слова."""
    out = {m.group(1).lower() for m in MENTION.finditer(text)}
    if words:
        out |= {w.lower() for w in WORD.findall(text)}
    return {u for u in out if u not in SKIP and valid(u)}


async def tg_channel(fr, channel, pages=30, log=None):
    """Посты публичного канала через веб-версию t.me/s/<канал>, страница за страницей назад."""
    channel = channel.strip().lstrip("@").replace("https://t.me/", "").replace("s/", "", 1).strip("/")
    found, before = set(), None
    for p in range(pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        r = await fr.get(url)
        if r.status_code in (301, 302):
            r = await fr.get(r.headers.get("location", url))
        soup = BeautifulSoup(r.text, "lxml")
        posts = soup.select(".tgme_widget_message")
        if not posts:
            break
        for post in posts:
            txt = post.select_one(".tgme_widget_message_text")
            body = (txt.get_text(" ") if txt else "") + " " + " ".join(a.get("href", "") for a in post.select("a"))
            found |= extract(body, words=False)
        ids = [int(m.group(1)) for x in posts if (m := re.search(r"/(\d+)$", x.get("data-post", "")))]
        if not ids or (before and min(ids) >= before):
            break
        before = min(ids)
        if log:
            log(f"📡 {channel}: стр. {p + 1}, найдено {len(found)}")
    found.discard(channel.lower())
    return found


async def collect(spec, fr, pages=30, log=None):
    """tg:канал[,канал2] · url:ссылка · file:путь. «+» в конце — добавить вариации каждого слова."""
    plus = spec.endswith("+")
    body = spec.split(":", 1)[1].rstrip("+").strip()
    names = set()
    if spec.startswith("tg:"):
        for ch in body.split(","):
            if ch.strip():
                names |= await tg_channel(fr, ch, pages, log)
    elif spec.startswith("url:"):
        url = body if body.startswith("http") else "https://" + body
        r = await fr.get(url)
        if r.status_code in (301, 302):
            r = await fr.get(r.headers.get("location", url))
        soup = BeautifulSoup(r.text, "lxml")
        names = extract(soup.get_text(" ") + " " + " ".join(a.get("href", "") for a in soup.select("a")))
    elif spec.startswith("file:"):
        if not os.path.exists(body):
            raise FileNotFoundError(body)
        names = extract(open(body, encoding="utf-8", errors="ignore").read())
    if plus:
        extra = set()
        for w in list(names)[:3000]:
            if len(w) <= 12:
                extra |= {m for m in mutations(w) if valid(m)}
        names |= extra
    return sorted(names)
