#!/usr/bin/env python3
"""Username Hunter — поиск и оценка юзов Telegram / Fragment в терминале.
Запуск без аргументов — интерактивное меню. Примеры:
  python cli.py hunt 5p -n 30 --min 65
  python cli.py check lomak tonix privet
  python cli.py info durov
  python cli.py market
  python cli.py db --export free.csv
"""
import argparse, asyncio, os, sys, time
from bootstrap import configure_stdio
configure_stdio()
from collections import Counter
from dotenv import load_dotenv
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich.text import Text
from rich import box

from fragment import Fragment
from market import Market
from scorer import rate, level, level_min, LEVELS
from generator import candidates, PRESETS, canonical_preset
from checker import Checker, LABEL, FREE, MAYBE, INVALID, TAKEN, FRAG_SALE, FRAG_AVAIL, FRAG_SOLD, ERROR
from db import DB
import settings as cfg
from updater import current_version

VERSION = current_version()

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
import logging
os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), exist_ok=True)
logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hunter.log"),
                    level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s", force=True)   # не мусорим в экран
logging.getLogger("telethon").setLevel(logging.ERROR)
con = Console()
GENERATION_SLICE_SECONDS = 0.25
SET = cfg.load()
_c = SET.get("concurrency", "auto")
CONC = "auto" if str(_c).lower() in ("auto", "0", "") else int(_c)

BANNER = r"""[bold cyan]
 _   _                                         _   _             _
| | | |___  ___ _ __ _ __   __ _ _ __ ___   ___| | | |_   _ _ __ | |_ ___ _ __
| | | / __|/ _ \ '__| '_ \ / _` | '_ ` _ \ / _ \ |_| | | | | '_ \| __/ _ \ '__|
| |_| \__ \  __/ |  | | | | (_| | | | | | |  __/  _  | |_| | | | | ||  __/ |
 \___/|___/\___|_|  |_| |_|\__,_|_| |_| |_|\___|_| |_|\__,_|_| |_|\__\___|_|
[/bold cyan][dim]             поиск · оценка · аналитика юзов Telegram / Fragment[/dim]"""
BANNER += f"\n[dim]v{VERSION} · GitHub Edition · меню u — обновление[/dim]"


# ───────────────────────── helpers ─────────────────────────
class App:
    def __init__(self):
        global app_ref
        app_ref = self
        self.fr = Fragment(CONC)
        self.mk = Market(self.fr)
        self.ck = Checker(self.fr, CONC)
        self.db = DB()

    async def market(self):
        if not self.mk.sold:
            with con.status("[cyan]Загружаю рынок Fragment…"):
                try:
                    await self.mk.load()
                except Exception as e:
                    con.print(f"[yellow]Не удалось загрузить рынок ({e}), оценки по модели[/]")
        return self.mk


def sc_color(s):
    return level(s)[2]


def lvl(s):
    g, name, color = level(s)
    return Text(f"{g:<2} {name}", style=color)


def ton(v, usd=None, short=False):
    if v is None:
        return "—"
    s = f"{v:,.0f} TON" if v >= 10 else f"{v:,.1f} TON"
    if usd and not short and SET.get("show_usd", True):
        s += f" [dim]~${v * usd:,.0f}[/dim]"
    return s


ST_STYLE = {FREE: "bold green", MAYBE: "yellow", INVALID: "dim", TAKEN: "red", FRAG_SALE: "magenta", FRAG_AVAIL: "cyan", FRAG_SOLD: "blue", ERROR: "dim"}


# похожие пресеты для авто-подбора (по порядку)
SIMILAR = {
    "5": ["5p", "b5", "6", "6p"], "5p": ["6p", "b5", "b6", "7p"], "6": ["6p", "b6", "7p"],
    "6p": ["7p", "b6", "b7"], "7p": ["b7", "mix"], "5d": ["6d", "b5", "5p"], "6d": ["5d", "b6", "6p"],
    "rep": ["5p", "6p"], "b5": ["b6", "5p", "b7"], "b6": ["b7", "6p", "7p"], "b7": ["7p", "mix"],
    "w5": ["w6", "w7", "w8", "dict"], "w6": ["w7", "w5", "w8", "dict"], "w7": ["w8", "w6", "dict"],
    "w8": ["dict"], "ru5": ["ru6", "ru7", "dict"], "ru6": ["ru7", "ru5", "dict"], "ru7": ["dict"],
    "niche": ["combo", "dict"], "combo": ["niche", "dict"], "dict": ["combo", "b6"], "mix": [],
}


# ───────────────────────── TELEGRAM API ─────────────────────────
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def setup_api():
    """Мастер: спросить API_ID/API_HASH и сохранить в .env."""
    con.print(Panel(
        "Чтобы показывать только юзы, которые [bold]точно встанут[/] (без «некорректное имя»),\n"
        "программа проверяет их через Telegram API от твоего аккаунта — так же, как поле «Имя пользователя».\n\n"
        "1. Открой [cyan]https://my.telegram.org[/] → войди по номеру\n"
        "2. [bold]API development tools[/] → заполни App title и Short name (любые) → Create\n"
        "3. Скопируй [bold]App api_id[/] и [bold]App api_hash[/] сюда",
        title="🔐 Подключение Telegram API (один раз)", border_style="yellow"))
    api_id = Prompt.ask("api_id").strip()
    api_hash = Prompt.ask("api_hash").strip()
    if not (api_id.isdigit() and len(api_hash) >= 20):
        con.print("[red]Похоже на ошибку в данных, попробуй ещё раз[/]")
        return False
    lines = [l for l in (open(ENV_PATH).read().splitlines() if os.path.exists(ENV_PATH) else [])
             if not l.startswith(("API_ID=", "API_HASH="))]
    lines += [f"API_ID={api_id}", f"API_HASH={api_hash}"]
    open(ENV_PATH, "w").write("\n".join(lines) + "\n")
    os.environ["API_ID"], os.environ["API_HASH"] = api_id, api_hash
    con.print("[green]Сохранено в .env. Сейчас Telegram пришлёт код — введи номер и код.[/]")
    return True


async def ensure_tg(app, ask=True):
    """Включает проверку через Telegram API. Если ключей нет — предлагает настроить."""
    if app.ck.tg:
        return True
    if not (os.getenv("API_ID") and os.getenv("API_HASH")):
        if not (ask and sys.stdin.isatty() and Confirm.ask(
                "[yellow]Telegram API не подключён — без него часть юзов будет «некорректное имя». Подключить сейчас?",
                default=True)):
            return False
        if not setup_api():
            return False
    ok = await app.ck.start_telethon(con.print)
    if ok:
        accs = app.ck.accounts
        con.print(f"[green]✓ Проверка через Telegram API включена: {len(accs)} акк. "
                  f"({', '.join(a.title for a in accs)})[/]")
        api_pause_note(app)
    return ok


def api_pause_note(app):
    t = app.ck.api_paused_until
    if t:
        left = t - time.time()
        con.print(Panel(
            f"Telegram дал флуд-лимит на проверку юзов: ещё [bold]{int(left // 3600)} ч {int(left % 3600 // 60)} мин[/] "
            f"(до {time.strftime('%d.%m %H:%M', time.localtime(t))}).\n"
            "Пока он не кончится, проверяю только по сайтам: найденные будут 🟡 «похоже свободен», "
            "их потом перепроверишь в меню 6.\n"
            "Чтобы не ждать — добавь второй аккаунт (меню 9): лимит у каждого свой.",
            title="⏳ Telegram API на паузе", border_style="yellow", expand=False))


def save_ready(names):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ready.txt")
    old = set(open(p).read().split()) if os.path.exists(p) else set()
    with open(p, "a", encoding="utf-8") as f:
        for nm in names:
            if nm not in old:
                f.write(nm + "\n")
    return p


# ───────────────────────── HUNT ─────────────────────────
async def hunt(app, spec=None, n=None, min_score=None, recheck=False, verify=False, telethon=None):
    s_ = dict(SET)
    if s_["max_score"] < s_["min_score"]:
        s_["max_score"] = 100
    spec = spec or s_["preset"]
    normalized = canonical_preset(spec)
    if normalized != spec:
        con.print(f"[dim]Пресет {spec} → {normalized}[/]")
        spec = normalized
    n = n or s_["target"]
    if min_score is not None:
        s_["min_score"] = min_score
    min_score = max(s_["min_score"], level_min(s_.get("min_level", "F")))
    telethon = s_["use_api"] if telethon is None else telethon
    if telethon:
        await ensure_tg(app)
    mk = await app.market()
    usd = mk.ton_usd
    WORD_MODES = ("w", "ru", "dict", "niche", "combo", "like:", "mix", "pair", "all", "tg:", "url:", "file:")
    auto = s_.get("auto_relax", True)
    ask_mode = s_.get("relax_ask", True) and sys.stdin.isatty()
    log = []
    if (s_["only_words"] or s_["niche"]) and not spec.startswith(WORD_MODES):
        new = "niche" if s_["niche"] else "dict"
        con.print(f"[yellow]Пресет «{spec}» генерирует случайные буквы, а включены "
                  f"{'ниши' if s_['niche'] else 'только слова'} — переключаю на «{new}»[/]")
        spec = new
    import itertools as _it
    import generator as G
    if spec.startswith(G.SOURCE_PREFIXES):              # парсинг: собираем юзы до начала проверки
        import sources
        try:
            with con.status(f"Парсю {spec}…") as stt:
                got = await sources.collect(spec, app.fr, s_["parse_pages"], lambda m: stt.update(m))
        except Exception as e:
            con.print(f"[red]Не удалось спарсить {spec}: {e}[/]")
            return
        G.EXTERNAL[spec] = got
        con.print(f"[green]Собрано {len(got)} юзов/слов из {spec}[/] — проверяю все")
        if not got:
            return
        s_["min_score"], s_["min_level"], s_["max_score"] = 0, "F", 100
        min_score = 0
        auto = False
        n = 0                                           # проверяем всё собранное
    app.ck.fast = s_["fast_check"]
    skipped = Counter()
    cur = {"spec": spec, "min": min_score, "desc": "", "gen": None, "since_free": 0, "s": dict(s_)}
    # Preflight can call ask_user before the checking loop starts.
    # Keep found initialized for both pause UI and Telegram notifications.
    found = []
    raw_stats = Counter()
    tried = []
    queue = [spec]

    def remember(sp):
        if sp not in tried:
            tried.append(sp)

    def next_specs(sp):
        if sp.startswith("like:"):
            return ["combo", "mix"]
        return SIMILAR.get(sp, ["mix"])

    async def prepare(sp, interactive, want=None):
        """Готовит генератор под пресет: подгоняет длину и порог. None — если пресет не подходит."""
        loc = dict(s_)
        if want is None:
            want = min_score
        else:                                           # уровень выбран вручную
            loc["min_score"], loc["min_level"] = want, "F"
        sample = []
        for name in candidates(sp, 0, prefix=loc["starts"], suffix=loc["ends"],
                               lengths=(loc["len_min"], loc["len_max"]), cooperative=True):
            if name is None:
                await asyncio.sleep(0)
                continue
            sample.append(name)
            if len(sample) >= 3000:
                break
        if not sample:
            return None
        lens = sorted({len(u) for u in sample})
        if not any(loc["len_min"] <= L <= loc["len_max"] for L in lens):
            msg = f"«{sp}» даёт длину {lens[0]}–{lens[-1]} → ставлю её"
            con.print(f"[yellow]⚠ {msg}[/]") if interactive else log.append(msg)
            loc["len_min"], loc["len_max"] = lens[0], lens[-1]
        ok_names = [u for u in sample if cfg.name_ok(u, loc)]
        if not ok_names:
            log.append(f"«{sp}» не проходит фильтры")
            return None
        best = max(rate(u).score for u in ok_names)
        if best < want:
            g, name, _ = level(best)
            new_min = max(0, best - 6)
            if interactive and not (auto and not ask_mode):
                con.print(f"[yellow]⚠ У «{sp}» лучшие варианты набирают скор ≈ {best} ({g} {name}), а в настройках нужно от {want}. "
                          f"С таким порогом этот пресет почти ничего не найдёт.[/]")
                if sys.stdin.isatty() and not Confirm.ask(f"Снизить порог до {new_min} (Enter — да, n — оставить и выйти)?", default=True):
                    return None
            msg = f"«{sp}» максимум скора {best} ({g}) → порог {want}→{new_min}"
            con.print(f"[yellow]🔄 {msg}[/]") if interactive else log.append("🔄 " + msg)
            want = new_min
            loc["min_score"], loc["min_level"] = new_min, "F"

        def gen():
            miss = 0
            for u in candidates(sp, want, prefix=loc["starts"], suffix=loc["ends"],
                                lengths=(loc["len_min"], loc["len_max"]), cooperative=True, metrics=raw_stats):
                if u is None:
                    yield None
                    continue
                ok = cfg.name_ok(u, loc) and cfg.value_ok(rate(u), mk.estimate(u)["mid"], loc)
                if not ok:
                    skipped["x"] += 1
                    miss += 1
                    if miss % 128 == 0:
                        yield None
                    if miss > 60000:
                        return
                    continue
                miss = 0
                yield u
        cur.update(spec=sp, min=want, desc=PRESETS.get(sp, (f"шаблон {sp}",))[0], gen=gen(), since_free=0, s=loc)
        return True

    def lower_level(m):
        """Следующий уровень ниже текущего порога: (порог, «A 🔥 Редкий») или None."""
        for mn, nm, g, _ in LEVELS:
            if mn < m:
                return mn, f"{g} {nm}"
        return None

    def next_preset():
        for sp in next_specs(cur["spec"]) + ["mix"]:
            if sp not in tried and sp != cur["spec"]:
                return sp
        return None

    def ask_user(reason, stag):
        """Пауза: что делать дальше. -> '0' стоп · '1' пресет ниже · '2' уровень ниже · '3' оба · '4' продолжать"""
        live = cur.get("live")
        nxt, low = next_preset(), lower_level(cur["min"])
        g, nm, _ = level(cur["min"])
        if live:
            live.stop()
        con.bell()
        if s_["notify_find"] and app.ck.tg and not cur.get("asked_tg"):
            cur["asked_tg"] = True
            asyncio.ensure_future(app.ck.notify(f"⏸ Поиск «{cur['spec']}» на паузе: {reason}. Нашёл {len(found)}. Жду выбора в программе."))
        opts = {}
        lines = [f"[bold]{reason}[/]  ·  сейчас: [bold]{cur['spec']}[/], уровень от [bold]{g} {nm}[/] ({cur['min']}+)  ·  найдено {len(found)}\n"]
        if nxt:
            opts["1"] = f"➡  Следующий пресет: [bold]{nxt}[/] — {PRESETS.get(nxt, ('',))[0]} (уровень тот же)"
        if low:
            opts["2"] = f"⬇  Уровень ниже: [bold]{low[1]}[/] ({low[0]}+), пресет тот же"
        if nxt and low:
            opts["3"] = f"⏬ Следующий пресет [bold]{nxt}[/] + уровень ниже [bold]{low[1]}[/]"
        if stag:
            opts["4"] = "🔁 Продолжать как есть"
        opts["0"] = "⏹  Остановить поиск"
        lines += [f"[bold cyan]{k}[/] {v}" for k, v in opts.items()]
        con.print(Panel("\n".join(lines), title="⏸ Что дальше?", border_style="yellow", expand=False))
        try:
            ch = Prompt.ask("Выбор", choices=list(opts), default=next(iter(opts)))
        except (KeyboardInterrupt, EOFError):
            ch = "0"
        if live:
            live.start()
        return ch, nxt, low

    async def switch(reason, stag=False):
        """Переход на похожий пресет / уровень ниже. False — остановиться."""
        if not auto:
            log.append(reason + " — смена пресета выключена")
            return False
        if cur["spec"].startswith(G.SOURCE_PREFIXES):
            log.append(reason)
            return False
        if ask_mode:
            while True:
                ch, nxt, low = ask_user(reason, stag)
                if ch == "0":
                    log.append("остановлено")
                    return False
                if ch == "4":
                    cur["since_free"] = 0
                    return True
                sp = nxt if ch in "13" else cur["spec"]
                want = low[0] if ch in "23" else cur["min"]
                old = (cur["spec"], cur["min"])
                if ch in "13":
                    remember(cur["spec"])
                if await prepare(sp, False, want):
                    log.append(f"✋ «{old[0]}» {old[1]}+ → «{sp}» {cur['min']}+")
                    return True
                # Keep the explicit choice even when its filters still produce no candidates.
                cur.update(spec=sp, min=want, gen=None,
                           desc=PRESETS.get(sp, (f"шаблон {sp}",))[0], since_free=0)
                cur["s"] = dict(cur["s"], min_score=want, min_level="F")
                stag = False  # No valid generator remains to "continue as is".
                remember(sp)
                reason = f"«{sp}» не подходит под фильтры"
        if cur["spec"] == "all":
            log.append(reason)
            return False
        remember(cur["spec"])
        for sp in next_specs(cur["spec"]) + ["mix"]:
            if sp in tried:
                continue
            old = cur["spec"]
            if await prepare(sp, False):
                log.append(f"🔄 {reason}: «{old}» → «{sp}»")
                return True
            remember(sp)
        log.append("все похожие пресеты перепробованы")
        return False

    con.print("[dim]Проверяю настройки…[/]")       # без спиннера — иначе он закрывает вопрос
    ok = await prepare(spec, True)
    if not ok:
        if not auto:
            con.print("[red]Ни один вариант не проходит фильтры. Проверь настройки.[/]")
            return
        if not await switch("пресет не подходит"):
            con.print("[red]Ничего не подходит под фильтры (длина/цифры/начало/буквы). Проверь настройки.[/]")
            return
    STAG = max(150, n * 3)      # столько проверок без находок → пробуем похожий пресет
    rdays = s_["recheck_days"]
    other, stats = [], Counter()
    t0 = time.time()
    done = False
    watch_new = [0]
    maybe_set = set()
    notified = [0]
    G.CURRENT[0] = None  # Preflight sampling must not look like active enumeration.

    def render():
        el = time.time() - t0
        chk = sum(stats.values())
        head = Table.grid(expand=True)
        for _ in range(6):
            head.add_column(justify="center")
        head.add_row(*[Text(x, style="dim") for x in
                       ["проверено", "🟢 точно встанут" if app.ck.tg else "🟡 похоже свободно",
                        "🔴 занято / ⚪ некорр.", "💎 Fragment", "скорость", "время"]])
        head.add_row(Text(str(chk), style="bold"), Text(f"{stats[FREE] + stats[MAYBE]}  (цель {n or '∞'})", style="bold green"),
                     Text(f"{stats[TAKEN]} / {stats[INVALID]}", style="red"),
                     Text(str(stats[FRAG_AVAIL] + stats[FRAG_SALE] + stats[FRAG_SOLD]), style="cyan"),
                     Text((f"{chk / el:.1f}/с" if el > 0 else "—") + f" · {app.ck.sem.mode} {int(app.ck.sem.limit)}п"
                          + ((f" · ⏳ API пауза до {time.strftime('%H:%M', time.localtime(app.ck.api_paused_until))}" if app.ck.api_paused_until else
                              f" · API {app.ck.api_checks} · {len(app.ck.accounts)} акк ({app.ck.delay:.2f}с)") if app.ck.tg else "")), Text(f"{int(el // 60)}:{int(el % 60):02d}"))
        t = Table(box=box.SIMPLE_HEAVY, expand=True, title=("🟢 Точно встанут — проверено через Telegram API (копируй как есть)" if app.ck.tg else "🟡 Похоже свободные (без Telethon — нужна перепроверка)"), title_style="bold green")
        t.add_column("#", style="dim", width=3)
        t.add_column("юз", style="bold")
        t.add_column("скор", justify="right")
        t.add_column("уровень", no_wrap=True)
        t.add_column("оценка", justify="right")
        t.add_column("почему", style="dim", overflow="ellipsis", no_wrap=True)
        for i, (nm, s, est) in enumerate(sorted(found, key=lambda x: -x[1].score)[:18], 1):
            t.add_row(str(i), ("🟡 " if nm in maybe_set else "") + nm, Text(str(s.score), style=sc_color(s.score)), lvl(s.score), ton(est, short=True),
                      ", ".join(r for r, _ in s.parts[:3]))
        f = Table(box=box.SIMPLE, expand=True, title="💎 Можно купить на Fragment", title_style="cyan")
        f.add_column("юз"); f.add_column("статус"); f.add_column("цена / мин. ставка", justify="right")
        f.add_column("оценка", justify="right"); f.add_column("скор", justify="right")
        for nm, st, s, est, price in sorted(other, key=lambda x: -x[2].score)[:6]:
            f.add_row(nm, LABEL[st], ton(price, short=True), ton(est, short=True),
                      Text(str(s.score), style=sc_color(s.score)))
        dist = Counter(level(x[1].score)[0] for x in found)
        lv = " ".join(f"{g}:{dist[g]}" for _, _, g, _ in LEVELS if dist[g])
        pk = G.CURRENT[0]
        prog = ""
        if pk and pk in G.PROGRESS:
            d, tot = G.PROGRESS[pk]
            prog = f"перебор {d / tot * 100:.2f}% из {tot:,} · ".replace(",", " ")
        foot = Text(
            f"состояние: {cur.get('phase', 'подготовка')} · " + prog.rstrip(' ·') + "\n"
            + f"оценено кандидатов: {raw_stats['total']} · отсев по скору: {raw_stats['low_score']} · "
            + f"фильтры: {skipped['x']} · уже в кэше базы: {skipped['cache']}\n"
            + f"уровни найденных: {lv or '—'} · "
            + (f"👁 в слежку +{watch_new[0]} · " if watch_new[0] else "") + " · ".join(log[-5:]),
            style="dim", overflow="ellipsis", no_wrap=True)
        parts = [head, t] + ([f] if s_["show_fragment"] else []) + [foot]
        return Panel(Group(*parts), title=f"[bold]Охота: {cur['spec']}[/] — {cur['desc']}, скор ≥ {cur['min']}"
                     + (f" [dim](пробовал: {', '.join(tried)})[/]" if tried else ""),
                     subtitle="[dim]Ctrl+C — остановить[/]", border_style="cyan")

    try:
        with Live(render(), console=con, refresh_per_second=4, transient=False, get_renderable=render) as live:
            cur["live"] = live
            while not done:
                if cur["since_free"] >= STAG:
                    if await switch(f"{cur['since_free']} проверок без находок", stag=True):
                        live.update(render())
                        continue
                    if ask_mode and auto:
                        break                               # выбрал «остановить»
                    cur["since_free"] = 0
                batch = []
                batch_started = time.monotonic()
                cur["phase"] = "отбор кандидатов"
                for u in cur["gen"]:
                    if u is None:
                        await asyncio.sleep(0)
                        if batch and time.monotonic() - batch_started >= GENERATION_SLICE_SECONDS:
                            break
                        continue
                    if recheck or rdays == 0 or not app.db.recent(u, rdays):
                        batch.append(u)
                    else:
                        skipped["cache"] += 1
                    if (len(batch) >= max(16, int(app.ck.sem.limit) * 4)
                            or (batch and time.monotonic() - batch_started >= GENERATION_SLICE_SECONDS)):
                        break
                if not batch:
                    details = []
                    if raw_stats['low_score']:
                        details.append(f"по скору отсеяно {raw_stats['low_score']}")
                    if skipped['x']:
                        details.append(f"по фильтрам {skipped['x']}")
                    if skipped['cache']:
                        details.append(f"уже проверено в базе {skipped['cache']}")
                    reason = f"«{cur['spec']}»: новых кандидатов нет"
                    if details:
                        reason += " · " + "; ".join(details)
                    if await switch(reason):
                        live.update(render())
                        continue
                    log.append("кандидаты закончились" + (f" (уже проверенные пропускаются {rdays} дн.)" if rdays else ""))
                    break
                cur["phase"] = f"ожидание ответов сайтов / API ({len(batch)} юзов)"
                for coro in asyncio.as_completed([app.ck.check(u) for u in batch]):
                    name, st, info = await coro
                    stats[st] += 1
                    s = rate(name)
                    est = mk.estimate(name)["mid"]
                    price = (info or {}).get("price") or (info or {}).get("min_bid")
                    if st != ERROR:
                        app.db.put(name, st, s.score, est, price)
                    if st == TAKEN and s_["watch_auto_add"] and s.score >= s_["watch_min_score"]:
                        if app.db.watch_add(name, s.score, "auto", s_["watch_max"]):
                            watch_new[0] += 1
                    log.append(f"{name}:{st}")
                    cur["since_free"] += 1
                    if st in (FREE, MAYBE):
                        cur["since_free"] = 0
                        found.append((name, s, est))
                        if st == MAYBE:
                            maybe_set.add(name)
                        if s_["beep"] and s.score >= 85:
                            con.bell()
                        if s_["notify_find"] and app.ck.tg and s.score >= level_min(s_["notify_level"]):
                            g, lname, _ = level(s.score)
                            sure = st == FREE
                            if await app.ck.notify(f"{'🟢' if sure else '🟡'} Найден юз @{name} — {g} {lname}, скор {s.score}, "
                                                   f"оценка ~{est:,.0f} TON\n"
                                                   + ("Свободен, можно ставить: Настройки → Имя пользователя"
                                                      if sure else "Похоже свободен — перепроверь")):
                                notified[0] += 1
                    elif st in (FRAG_AVAIL, FRAG_SALE) and s_["show_fragment"] and (price or 0) <= s_["frag_max"]:
                        other.append((name, st, s, est, price))
                    live.update(render())
                    if n and len(found) >= n:
                        done = True
            live.update(render())
    except KeyboardInterrupt:
        pass
    con.print()
    if app.ck.tg and found:
        ready = [f[0] for f in sorted(found, key=lambda x: -x[1].score) if f[0] not in maybe_set]
        if maybe_set:
            con.print(Panel("\n".join(sorted(maybe_set, key=lambda x: -rate(x).score)),
                            title="🟡 Похоже свободны — API был на паузе, перепроверь в меню 6", border_style="yellow", expand=False))
        if ready:
            con.print(Panel("\n".join(ready), title="🟢 Точно встанут (без @, копируй)", border_style="green", expand=False))
            con.print(f"[dim]Также сохранено в {save_ready(ready)}[/]")
    con.print(f"[green]Готово:[/] {len(found)} свободных из {sum(stats.values())} проверенных. "
              f"Всё сохранено в базе ([cyan]python cli.py db[/]).")
    if notified[0] and app.ck.tg:
        await app.ck.notify(f"🏁 Поиск закончен: найдено {len(found)}, отправил тебе {notified[0]} лучших "
                            f"(проверено {sum(stats.values())}).")
    if watch_new[0]:
        con.print(f"[dim]👁 {watch_new[0]} занятых хороших юзов добавлено в слежку (меню 8)[/]")
    if found and s_["auto_export"]:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", time.strftime("found_%Y%m%d.csv"))
        import csv
        new = not os.path.exists(p)
        with open(p, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["username", "score", "estimate_ton", "verified"])
            w.writerows([[nm, sc.score, round(e, 1), int(bool(app.ck.tg))] for nm, sc, e in found])
        con.print(f"[dim]CSV: {p}[/]")
    if found and app.ck.tg is None:
        con.print("[yellow]⚠ Без Telethon «похоже свободен» = сайт не видит владельца. Это может быть скрытый, "
                  "удалённый или зарезервированный юз (особенно частые слова). Перепроверь через Telegram API.[/]")
    if found and app.ck.tg is None and (verify or (os.getenv("API_ID") and sys.stdin.isatty() and
                             Confirm.ask("Перепроверить найденные через Telethon (100% точно)?", default=True))):
        await verify_telethon(app, [f[0] for f in sorted(found, key=lambda x: -x[1].score)])


async def verify_telethon(app, names):
    if not await ensure_tg(app):
        return
    if app.ck.api_paused_until:
        api_pause_note(app)
        return
    ready = []
    t = Table(title="Проверка через Telegram API", box=box.ROUNDED)
    t.add_column("юз", style="bold"); t.add_column("результат"); t.add_column("скор", justify="right")
    with con.status("Проверяю…"):
        for nm in names:
            st = await app.ck.telethon_check(nm)
            s = rate(nm)
            app.db.put(nm, st, s.score, app.mk.estimate(nm)["mid"], verified=1)
            t.add_row(nm, Text(LABEL[st], style=ST_STYLE.get(st, "")), str(s.score))
            if st == FREE:
                ready.append(nm)
    con.print(t)
    if ready:
        con.print(Panel("\n".join(ready), title="🟢 Точно встанут (без @, копируй)", border_style="green", expand=False))
        save_ready(ready)


# ───────────────────────── CHECK LIST ─────────────────────────
async def check_list(app, names):
    mk = await app.market()
    names = [x.lower().lstrip("@") for x in names if x.strip()]
    with con.status(f"Проверяю {len(names)}…"):
        res = await asyncio.gather(*(app.ck.check(n) for n in names))
    t = Table(box=box.ROUNDED, title="Результаты проверки")
    for c, j in [("юз", "left"), ("статус", "left"), ("скор", "right"), ("уровень", "left"),
                 ("оценка", "right"), ("цена / посл. продажа", "right")]:
        t.add_column(c, justify=j)
    for name, st, info in sorted(res, key=lambda r: -rate(r[0]).score):
        s = rate(name); e = mk.estimate(name)
        price = info.get("price") or info.get("min_bid") if info else None
        if st != ERROR:
            app.db.put(name, st, s.score, e["mid"], price)
        if st == TAKEN and SET["watch_auto_add"] and s.score >= SET["watch_min_score"]:
            app.db.watch_add(name, s.score, "auto", SET["watch_max"])
        t.add_row(f"[bold]{name}[/]", Text(LABEL[st], style=ST_STYLE.get(st, "")),
                  Text(str(s.score), style=sc_color(s.score)), lvl(s.score), ton(e["mid"], mk.ton_usd), ton(price))
    con.print(t)


# ───────────────────────── INFO ─────────────────────────
async def info(app, name):
    mk = await app.market()
    name = name.lower().lstrip("@")
    with con.status("Загружаю…"):
        _, st, inf = await app.ck.check(name, full=True)
    s = rate(name); e = mk.estimate(name)
    usd = mk.ton_usd
    br = Table(box=box.SIMPLE, show_header=False)
    br.add_column(); br.add_column(justify="right")
    br.add_row("база", "40")
    for r, p in s.parts:
        br.add_row(r, Text(f"{p:+}", style="green" if p > 0 else "red" if p < 0 else "dim"))
    br.add_row("[bold]итого", Text(str(s.score), style=sc_color(s.score)))
    lines = [f"Статус: {LABEL[st]}  [dim]({inf.get('raw_status', '')})[/]" if inf else f"Статус: {LABEL[st]}"]
    if inf and inf.get("price"):
        lab = "Последняя продажа" if st == FRAG_SOLD else "Цена на Fragment"
        lines.append(f"{lab}: [bold]{ton(inf['price'], usd)}[/]")
    if inf and inf.get("min_bid"):
        lines.append(f"Мин. ставка (оценка Telegram): [bold]{ton(inf['min_bid'], usd)}[/]")
    lines.append(f"Моя оценка: [bold]{ton(e['low'], usd, True)} – {ton(e['high'], usd, True)}[/]  "
                 f"(≈ [bold cyan]{ton(e['mid'], usd)}[/])")
    lines.append(f"[dim]Источник: {e['source']}[/]")
    p = inf.get("price") if inf and st == FRAG_SALE else None
    if p:
        r = e["mid"] / p
        v = "[green]🟢 недооценён" if r >= 1.4 else "[red]🔴 переоценён" if r < 0.7 else "[yellow]🟡 по рынку"
        lines.append(f"Вердикт: {v}[/] (x{r:.2f})")
    if st == FREE:
        lines.append("[green]Можно занять бесплатно: Настройки → Имя пользователя[/]")
    if st == MAYBE:
        lines.append("[yellow]Сайт не видит владельца — проверь через Telethon или попробуй поставить в Telegram[/]")
    hist = Table(box=box.SIMPLE, title="История / ставки", title_style="dim")
    for hd in (inf or {}).get("history_head", [])[:4]:
        hist.add_column(hd)
    for row in (inf or {}).get("history", [])[:6]:
        hist.add_row(*[c[:28] for c in row[:4]])
    con.print(Panel(Group(Text.from_markup(f"[bold]{name}[/]  [{level(s.score)[2]}]{level(s.score)[0]} · {s.tier}[/]  скор {s.score}/100"), *[Text.from_markup(l) for l in lines]),
                    title="Сводка", border_style="cyan"))
    con.print(Panel(br, title="Разбор скора", border_style="dim"))
    if (inf or {}).get("history"):
        con.print(hist)
    con.print(f"[dim]{inf.get('url', '') if inf else ''}[/]")


# ───────────────────────── MARKET ─────────────────────────
async def market_screen(app, refresh=False):
    if refresh:
        with con.status("Обновляю рынок…"):
            await app.mk.load(force=True)
    mk = await app.market()
    usd = mk.ton_usd
    con.print(f"[dim]Курс TON: ${usd:.2f} · продаж в выборке: {len(mk.sold)} · лотов: {len(mk.sale)} · аукционов: {len(mk.auction)}[/]")
    t = Table(title="📊 Последние продажи по длине", box=box.ROUNDED)
    for c in ["длина", "продаж", "медиана", "среднее", "макс"]:
        t.add_column(c, justify="right")
    for k, (cnt, med, avg, mx) in mk.stats_by_length().items():
        t.add_row(f"{k}{'+' if k == 9 else ''}", str(cnt), ton(med), ton(avg), ton(mx))
    top = Table(title="🏆 Самые дорогие недавние продажи", box=box.ROUNDED)
    top.add_column("юз", style="bold"); top.add_column("цена", justify="right"); top.add_column("скор", justify="right")
    for it in sorted([x for x in mk.sold if x.get("price")], key=lambda x: -x["price"])[:10]:
        top.add_row(it["username"], ton(it["price"], usd), Text(str(it["score"]), style=sc_color(it["score"])))
    con.print(t, top)
    for which, title in (("sale", "💰 Недооценённые лоты (продажа)"), ("auction", "🔨 Недооценённые аукционы")):
        d = [x for x in mk.deals(which, SET["deal_ratio"], SET["deal_min_score"]) if x["price"] <= SET["frag_max"]]
        tt = Table(title=title, box=box.ROUNDED)
        for c in ["юз", "скор", "цена", "оценка", "x", "ссылка"]:
            tt.add_column(c)
        for it in d[:12]:
            tt.add_row(f"[bold]{it['username']}", Text(str(it["score"]), style=sc_color(it["score"])),
                       ton(it["price"]), ton(it["est"]), f"[green]x{it['ratio']:.1f}", f"[dim]{it['url']}")
        con.print(tt if d else f"[dim]{title}: сейчас нет[/]")


# ───────────────────────── DB ─────────────────────────
def db_screen(app, export=None, min_score=0, status="free,maybe"):
    c = app.db.counts()
    con.print("[dim]В базе: " + " · ".join(f"{LABEL.get(k, k)}: {v}" for k, v in c.items()) + "[/]")
    t = Table(title="Лучшие находки из базы", box=box.ROUNDED)
    for col in ["юз", "статус", "скор", "уровень", "оценка", "цена", "когда"]:
        t.add_column(col)
    for name, st, s, est, price, ver, ts in app.db.best(status, 40, min_score):
        t.add_row(f"[bold]{name}", Text(LABEL.get(st, st), style=ST_STYLE.get(st, "")), Text(str(s), style=sc_color(s)), lvl(s), ton(est), ton(price),
                  time.strftime("%d.%m %H:%M", time.localtime(ts)))
    con.print(t)
    if export:
        con.print(f"[green]Экспортировано {app.db.export(export, status)} → {export}[/]")


# ───────────────────────── SETTINGS ─────────────────────────
def fmt_val(kind, v):
    if kind == "bool":
        return "[green]вкл[/]" if v else "[red]выкл[/]"
    if v in ("", 0, 0.0) and kind in ("str", "float"):
        return "[dim]—[/]"
    return str(v)


app_ref = type("X", (), {})()


def settings_screen():
    global SET, CONC
    while True:
        t = Table(box=box.ROUNDED, title="⚙  Настройки", title_style="bold")
        t.add_column("#", style="bold cyan", justify="right"); t.add_column("параметр")
        t.add_column("значение", style="bold"); t.add_column("подсказка", style="dim")
        idx = {}
        for row in cfg.SCHEMA:
            k, label, kind, _, hint = row
            if label is None:
                t.add_row("", f"[bold magenta]{k}[/]", "", "")
                continue
            i = str(len(idx) + 1)
            idx[i] = row
            t.add_row(i, label, fmt_val(kind, SET[k]), hint)
        con.print(t)
        con.print("[dim]Уровни:[/] " + "  ".join(f"[{col}]{g} {n} ({mn}+)[/]" for mn, n, g, col in LEVELS))
        prof = "  ".join(f"[bold cyan]p{k}[/] {v[0]}" for k, v in cfg.PROFILES.items())
        con.print(f"[dim]Профили:[/] {prof}")
        con.print("[dim]Номер — изменить · p1..p8 — применить профиль · r — сбросить · 0 — назад[/]")
        ch = Prompt.ask("Выбор", default="0").strip().lower()
        if ch == "0":
            break
        if ch == "r":
            if Confirm.ask("Сбросить все настройки?", default=False):
                SET = dict(cfg.DEFAULTS)
        elif ch.startswith("p") and ch[1:] in cfg.PROFILES:
            name, vals = cfg.PROFILES[ch[1:]]
            SET.update(vals)
            con.print(f"[green]Профиль «{name}» применён[/]")
        elif ch in idx:
            k, label, kind, _, hint = idx[ch]
            if kind == "bool":
                SET[k] = not SET[k]
            else:
                if k == "preset":
                    con.print(presets_table())
                raw = Prompt.ask(f"{label} [dim]({hint})[/]", default=str(SET[k]))
                try:
                    SET[k] = cfg.parse(kind, raw)
                except Exception as e:
                    con.print(f"[red]Неверное значение: {e}[/]")
        else:
            con.print("[red]Нет такого пункта[/]")
        if SET["len_min"] > SET["len_max"]:
            SET["len_max"] = SET["len_min"]
        if SET["max_score"] < SET["min_score"]:
            con.print(f"[yellow]Макс. скор ({SET['max_score']}) меньше минимального — поставил 100[/]")
            SET["max_score"] = 100
        if SET["price_max"] and SET["price_max"] < SET["price_min"]:
            con.print("[yellow]«Оценка до» меньше «Оценки от» — убрал лимит[/]")
            SET["price_max"] = 0
        cfg.save(SET)
        CONC = SET["concurrency"]
        if hasattr(app_ref, "ck"):
            from limiter import AutoLimiter
            app_ref.ck.sem = AutoLimiter(start=8, fixed=None if CONC == "auto" else int(CONC))
            app_ref.fr.limiter = app_ref.ck.sem


def settings_summary():
    s = SET
    bits = [f"[bold]{s['preset']}[/]", f"найти {s['target']}", f"уровень от {s.get('min_level', 'F')}", f"скор {s['min_score']}–{s['max_score']}",
            f"длина {s['len_min']}–{s['len_max']}"]
    if s["price_min"] or s["price_max"]:
        bits.append(f"оценка {s['price_min']:g}–{s['price_max'] or '∞'} TON")
    if s["digits"] != "any":
        bits.append({"no": "без цифр", "only_end": "цифры в конце"}[s["digits"]])
    for k, lab in (("starts", "нач."), ("ends", "кон."), ("contains", "есть"), ("exclude", "нет")):
        if s[k]:
            bits.append(f"{lab} {s[k]}")
    if s["only_words"]:
        bits.append("только слова")
    if s["niche"]:
        bits.append("ниши")
    bits.append("API ✓" if s["use_api"] else "без API")
    bits.append("скорость: авто" if str(s.get("concurrency")) == "auto" else f"скорость: {s['concurrency']} потоков")
    return " · ".join(bits)


# ───────────────────────── WATCH (уходящие юзы) ─────────────────────────
def watch_add_names(app, names):
    added = 0
    for nm in names:
        nm = nm.strip().lower().lstrip("@")
        if nm:
            added += app.db.watch_add(nm, rate(nm).score, "manual")
    con.print(f"[green]Добавлено в слежку: {added}[/]" + (f" [dim](остальные уже были)[/]" if added < len(names) else ""))


def watch_import(app, min_score=None):
    m = SET["watch_min_score"] if min_score is None else min_score
    rows = app.db.taken_good(m, SET["watch_max"])
    n = sum(app.db.watch_add(nm, sc, "auto", SET["watch_max"]) for nm, sc in rows)
    con.print(f"[green]Из базы добавлено занятых со скором ≥ {m}: {n}[/]")


def ago(ts):
    if not ts:
        return "—"
    d = time.time() - ts
    return f"{int(d)}с" if d < 60 else f"{int(d // 60)}м" if d < 3600 else f"{int(d // 3600)}ч" if d < 86400 else f"{int(d // 86400)}д"


def watch_list(app, limit=60):
    total, fr = app.db.watch_count()
    t = Table(title=f"👁 В слежке: {total} · освободилось {fr or 0}", box=box.ROUNDED)
    for col in ["юз", "скор", "уровень", "статус", "проверок", "посл. проверка", "откуда"]:
        t.add_column(col)
    for nm, sc, added, last, st, n, freed, src in app.db.watch_list(limit):
        t.add_row(f"[bold]{nm}", Text(str(sc), style=sc_color(sc)), lvl(sc),
                  Text(LABEL.get(st, st), style=ST_STYLE.get(st, "")), str(n), ago(last) + (" назад" if last else ""),
                  "вручную" if src == "manual" else "из поиска")
    con.print(t)
    if total > limit:
        con.print(f"[dim]…и ещё {total - limit}[/]")


async def watch_run(app):
    total, _ = app.db.watch_count()
    if not total:
        con.print("[yellow]Список слежки пуст. Добавь юзы вручную или из базы (меню 8 → 3/5), "
                  "или просто ищи — занятые хорошие юзы запоминаются сами.[/]")
        return
    if SET["use_api"]:
        await ensure_tg(app)
    iv = SET["watch_interval"]
    stats, events, freed = Counter(), [], []
    t0, rnd = time.time(), [0, 0, 0]       # раунд, проверено в раунде, всего в раунде

    async def one(nm):
        name, st, info = await app.ck.check(nm)
        stats[st] += 1
        if st == ERROR or (st == MAYBE and app.ck.accounts):     # API на паузе — не поднимаем ложную тревогу
            return
        s = rate(name)
        app.db.put(name, st, s.score, app.mk.estimate(name)["mid"], (info or {}).get("price"), verified=int(st == FREE))
        if app.db.watch_set(name, st):
            sure = st == FREE
            freed.append((name, s.score, sure, time.time()))
            events.append(f"[bold green]🎉 {name} освободился![/]" if sure else f"[yellow]🟡 {name} — похоже освободился[/]")
            if SET["beep"]:
                con.bell()
            if SET["notify_tg"] and app.ck.tg:
                await app.ck.notify(("🎉 Освободился юз" if sure else "🟡 Похоже освободился юз") +
                                    f" @{name} (скор {s.score})\nЗанимай: Настройки → Имя пользователя\nhttps://t.me/{name}")
        elif st not in (TAKEN,):
            events.append(f"{name}: {LABEL.get(st, st)}")

    def render():
        total, fr = app.db.watch_count()
        nxt = app.db.watch_next()
        wait = max(0, (nxt or 0) + iv * 60 - time.time())
        head = Table.grid(expand=True)
        for _ in range(5):
            head.add_column(justify="center")
        head.add_row(*[Text(x, style="dim") for x in ["в слежке", "раунд", "🔴 занято", "🎉 освободилось", "следующий раунд"]])
        head.add_row(Text(str(total), style="bold"), Text(f"#{rnd[0]}  {rnd[1]}/{rnd[2]}"),
                     Text(str(stats[TAKEN]), style="red"), Text(str(len(freed)), style="bold green"),
                     Text("идёт проверка" if rnd[1] < rnd[2] else f"через {int(wait // 60)}:{int(wait % 60):02d}"))
        ft = Table(box=box.SIMPLE_HEAVY, expand=True, title="🎉 Освободились (занимай быстрее!)", title_style="bold green")
        ft.add_column("юз", style="bold"); ft.add_column("скор", justify="right"); ft.add_column("уровень")
        ft.add_column("точно?"); ft.add_column("когда")
        for nm, sc, sure, ts in sorted(freed, key=lambda x: -x[3])[:12]:
            ft.add_row(nm, Text(str(sc), style=sc_color(sc)), lvl(sc), "🟢 API" if sure else "🟡 сайт",
                       time.strftime("%H:%M:%S", time.localtime(ts)))
        acc = " · ".join(f"{a.title}: {a.state}" for a in app.ck.accounts) or "без Telegram API (только сайты)"
        parts = [head, ft if freed else Text("Пока никто не освободился — жду…", style="dim"),
                 Text.from_markup("[dim]" + " · ".join(events[-4:]) + "[/]" if events else ""),
                 Text(f"аккаунты: {acc} · уведомления в TG: {'вкл' if SET['notify_tg'] and app.ck.tg else 'выкл'}",
                      style="dim", overflow="ellipsis", no_wrap=True)]
        return Panel(Group(*parts), title=f"[bold]👁 Слежка за уходящими юзами[/] — проверка каждые {iv} мин",
                     subtitle=f"[dim]работает {int((time.time() - t0) // 60)} мин · Ctrl+C — остановить[/]",
                     border_style="green")

    try:
        with Live(render(), console=con, refresh_per_second=2, transient=False) as live:
            while True:
                due = app.db.watch_due(iv)
                if not due:
                    await asyncio.sleep(1)
                    live.update(render())
                    continue
                rnd[0] += 1
                rnd[1], rnd[2] = 0, len(due)
                step = max(8, int(app.ck.sem.limit) * 2)
                for i in range(0, len(due), step):
                    for coro in asyncio.as_completed([one(nm) for nm in due[i:i + step]]):
                        await coro
                        rnd[1] += 1
                        live.update(render())
    except KeyboardInterrupt:
        pass
    if freed:
        con.print(Panel("\n".join(f[0] for f in freed), title="🎉 Освободились (без @)", border_style="green", expand=False))
        save_ready([f[0] for f in freed if f[2]])


async def watch_menu(app):
    while True:
        total, fr = app.db.watch_count()
        con.print(Panel(
            "[bold]1[/] ▶  Запустить слежку\n[bold]2[/] 📋 Список\n[bold]3[/] ➕ Добавить юзы\n[bold]4[/] ➖ Удалить юзы\n"
            "[bold]5[/] 📥 Добавить занятые хорошие из базы\n[bold]6[/] 🧹 Очистить список\n[bold]0[/] назад\n\n"
            f"[dim]Проверка каждые {SET['watch_interval']} мин · авто-добавление: "
            f"{'вкл, скор ≥ ' + str(SET['watch_min_score']) if SET['watch_auto_add'] else 'выкл'} · "
            f"уведомления в TG: {'вкл' if SET['notify_tg'] else 'выкл'} (меняется в Настройках)[/]",
            title=f"👁 Уходящие юзы — {total} в слежке, освободилось {fr or 0}", border_style="green", expand=False))
        ch = Prompt.ask("Выбор", choices=list("0123456"), default="1")
        if ch == "0":
            return
        if ch == "1":
            await watch_run(app)
        elif ch == "2":
            watch_list(app)
        elif ch == "3":
            raw = Prompt.ask("Юзы через пробел (или путь к .txt)")
            watch_add_names(app, open(raw).read().split() if os.path.exists(raw) else raw.replace(",", " ").split())
        elif ch == "4":
            n = app.db.watch_remove([x.lower().lstrip("@") for x in Prompt.ask("Какие удалить (через пробел)").replace(",", " ").split()])
            con.print(f"Удалено: {n}")
        elif ch == "5":
            watch_import(app, IntPrompt.ask("Мин. скор", default=SET["watch_min_score"]))
        elif ch == "6" and Confirm.ask("Удалить весь список слежки?", default=False):
            app.db.watch_remove([r[0] for r in app.db.watch_list(10 ** 6)])


# ───────────────────────── ACCOUNTS ─────────────────────────
async def accounts_screen(app):
    if not (os.getenv("API_ID") and os.getenv("API_HASH")) and not setup_api():
        return
    if not app.ck.accounts:
        await ensure_tg(app, ask=False)
    while True:
        t = Table(title="👥 Аккаунты для проверки через Telegram API", box=box.ROUNDED)
        for col in ["#", "аккаунт", "файл", "статус", "проверок", "пауза"]:
            t.add_column(col)
        for i, a in enumerate(app.ck.accounts, 1):
            t.add_row(str(i), a.title, a.name, a.state, str(a.checks), f"{a.delay:.2f}с")
        con.print(t)
        con.print("[dim]Чем больше аккаунтов — тем быстрее проверка и меньше флуд-лимитов: запросы идут параллельно, "
                  "а если один словил лимит — работают остальные. Ключ API_ID/API_HASH тот же, новый не нужен.[/]")
        ch = Prompt.ask("[bold]a[/] — добавить · [bold]d N[/] — удалить · [bold]0[/] — назад", default="0").strip().lower()
        if ch in ("0", ""):
            return
        if ch == "a":
            con.print("[dim]Войди в другой аккаунт Telegram: номер → код придёт в Telegram этого аккаунта "
                      "(→ пароль, если включена 2FA). Сессия хранится только у тебя в data/sessions/.[/]")
            acc = await app.ck.add_account(
                lambda: Prompt.ask("Номер телефона (+7…)").strip(),
                lambda: Prompt.ask("Код из Telegram").strip(),
                lambda: Prompt.ask("Пароль 2FA", password=True),
                con.print)
            if acc:
                con.print(f"[green]✓ Добавлен: {acc.title}. Всего аккаунтов: {len(app.ck.accounts)}[/]")
        elif ch.startswith("d"):
            num = ch[1:].strip()
            if num.isdigit() and 1 <= int(num) <= len(app.ck.accounts):
                a = app.ck.accounts[int(num) - 1]
                if Confirm.ask(f"Удалить «{a.title}» (сеанс будет завершён)?", default=False):
                    await app.ck.remove_account(a)
                    con.print("[green]Удалён[/]")
            else:
                con.print("[red]Нет такого номера[/]")


# ───────────────────────── MENU ─────────────────────────
def presets_table():
    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column(style="bold cyan"); t.add_column(style="dim")
    for k, (d, _) in PRESETS.items():
        t.add_row(k, d)
    t.add_row("свой", "L буква · C согл. · V гласн. · D цифра · A буква/цифра (напр. CVCVC, tonDD, xLLLx)")
    return t


async def menu(app):
    con.print(BANNER)
    await ensure_tg(app)
    while True:
        c = app.db.counts()
        con.print(Panel(
            "[bold]1[/] 🔎 Найти свободные юзы\n[bold]2[/] ✅ Проверить список юзов\n[bold]3[/] 🔬 Подробно об одном юзе\n"
            "[bold]4[/] 📊 Рынок Fragment и выгодные лоты\n[bold]5[/] 🗂  Мои находки (база)\n[bold]6[/] 🔐 Перепроверить находки через Telethon\n"
            "[bold]7[/] ⚙  Настройки и профили\n[bold]8[/] 👁  Уходящие юзы (слежка)\n[bold]9[/] 👥 Аккаунты Telegram\n[bold]p[/] 📡 Парсинг: канал / сайт / файл → проверить все юзы\n[bold]u[/] ⬆ Обновить программу\n[bold]d[/] 🩺 Диагностика\n[bold]0[/] выход\n\n"
            f"[dim]Поиск: {settings_summary()}[/]",
            title="Меню", subtitle=f"[dim]в базе: ✓{c.get(FREE, 0)} свободных · {c.get(MAYBE, 0)} кандидатов[/]", border_style="cyan", expand=False))
        ch = Prompt.ask("Выбор", choices=list("0123456789pud"), default="1")
        try:
            if ch == "0":
                return
            if ch == "u":
                return "update"
            if ch == "d":
                import doctor
                doctor.main([])
                continue
            if ch == "1":
                con.print(f"[dim]Текущие настройки: {settings_summary()}[/]")
                if Confirm.ask("Искать с этими настройками?", default=True):
                    await hunt(app)
                else:
                    settings_screen()
            elif ch == "2":
                raw = Prompt.ask("Юзы через пробел (или путь к .txt)")
                names = open(raw).read().split() if os.path.exists(raw) else raw.replace(",", " ").split()
                await check_list(app, names)
            elif ch == "3":
                await info(app, Prompt.ask("Юз"))
            elif ch == "4":
                await market_screen(app, Confirm.ask("Обновить данные с Fragment?", default=False))
            elif ch == "5":
                m = IntPrompt.ask("Мин. скор", default=0)
                exp = Prompt.ask("Экспорт в CSV (имя файла или Enter — нет)", default="")
                db_screen(app, exp or None, m)
            elif ch == "7":
                settings_screen()
            elif ch == "8":
                await watch_menu(app)
            elif ch == "9":
                await accounts_screen(app)
            elif ch == "p":
                con.print("[dim]Примеры: [bold]tg:usernames_channel[/] (все @юзы и t.me-ссылки из постов) · "
                          "[bold]tg:кан1,кан2[/] · [bold]url:https://сайт[/] · [bold]file:list.txt[/] · "
                          "«+» в конце — ещё и вариации каждого слова[/]")
                src = Prompt.ask("Источник").strip()
                if not src.startswith(("tg:", "url:", "file:")):
                    src = ("file:" if os.path.exists(src) else "url:" if "." in src else "tg:") + src
                await hunt(app, src)
            elif ch == "6":
                rows = app.db.best(MAYBE, IntPrompt.ask("Сколько лучших перепроверить", default=20))
                await verify_telethon(app, [r[0] for r in rows if not r[5]])
        except KeyboardInterrupt:
            con.print("[yellow]Прервано[/]")


async def main(argv):
    p = argparse.ArgumentParser(description="Username Hunter — поиск и оценка юзов Telegram/Fragment")
    p.add_argument("--version", action="version", version=f"Username Hunter {VERSION}")
    sub = p.add_subparsers(dest="cmd")
    h = sub.add_parser("hunt", help="найти свободные (по умолчанию — из настроек)"); h.add_argument("spec", nargs="?")
    h.add_argument("-n", type=int); h.add_argument("--min", type=int)
    h.add_argument("--price-min", type=float); h.add_argument("--price-max", type=float)
    h.add_argument("--starts"); h.add_argument("--ends"); h.add_argument("--contains"); h.add_argument("--exclude")
    h.add_argument("--no-digits", action="store_true"); h.add_argument("--words", action="store_true")
    h.add_argument("--len", help="диапазон длины, напр. 5-6")
    h.add_argument("--recheck", action="store_true", help="перепроверять уже проверенные")
    h.add_argument("--verify", action="store_true", help="в конце проверить через Telethon")
    h.add_argument("--no-api", action="store_true", help="не проверять через Telegram API (быстрее, но неточно)")
    h.add_argument("--reset", action="store_true", help="начать полный перебор заново (сбросить прогресс)")
    c = sub.add_parser("check", help="проверить список"); c.add_argument("names", nargs="+")
    i = sub.add_parser("info", help="подробно об одном"); i.add_argument("name")
    m = sub.add_parser("market", help="рынок и выгодные лоты"); m.add_argument("--refresh", action="store_true")
    d = sub.add_parser("db", help="мои находки"); d.add_argument("--export"); d.add_argument("--min", type=int, default=0)
    d.add_argument("--status", default="free,maybe", help="free,maybe,taken,fragment,on_sale,nft")
    r = sub.add_parser("rate", help="только скор, без интернета"); r.add_argument("names", nargs="+")
    sub.add_parser("presets", help="список пресетов")
    sub.add_parser("setup", help="подключить Telegram API")
    sub.add_parser("settings", help="настройки и профили")
    w = sub.add_parser("watch", help="слежка за уходящими юзами: watch [run|add|rm|list|import] [юзы]")
    w.add_argument("action", nargs="?", default="run", choices=["run", "add", "rm", "list", "import"])
    w.add_argument("names", nargs="*")
    w.add_argument("--min", type=int, help="для import: мин. скор")
    sub.add_parser("accounts", help="аккаунты Telegram для проверки")
    u = sub.add_parser("update", help="обновить программу, сохранив личные данные")
    u.add_argument("--check", action="store_true")
    u.add_argument("--yes", action="store_true")
    sub.add_parser("doctor", help="локальная диагностика без вывода секретов")
    a = p.parse_args(argv)

    if a.cmd == "update":
        import updater
        raise SystemExit(updater.main((["--check"] if a.check else []) + (["--yes"] if a.yes else [])))
    if a.cmd == "doctor":
        import doctor
        raise SystemExit(doctor.main([]))
    if a.cmd == "setup":
        if setup_api():
            app = App(); await ensure_tg(app); await app.fr.close()
            await app.ck.close()
        return
    if a.cmd == "settings":
        return settings_screen()
    if a.cmd == "presets":
        return con.print(presets_table())
    if a.cmd == "rate":
        t = Table(box=box.ROUNDED)
        for col in ["юз", "скор", "уровень", "разбор"]:
            t.add_column(col)
        for s in sorted((rate(x) for x in a.names), key=lambda s: -s.score):
            t.add_row(s.username, Text(str(s.score), style=sc_color(s.score)), lvl(s.score), ", ".join(s.reasons))
        return con.print(t)
    app = App()
    requested = None
    try:
        if a.cmd is None:
            requested = await menu(app)
        elif a.cmd == "hunt":
            for k, v in (("price_min", a.price_min), ("price_max", a.price_max), ("starts", a.starts),
                         ("ends", a.ends), ("contains", a.contains), ("exclude", a.exclude)):
                if v is not None:
                    SET[k] = v
            if a.no_digits:
                SET["digits"] = "no"
            if a.words:
                SET["only_words"] = True
            if a.len:
                lo, _, hi = a.len.partition("-")
                SET["len_min"], SET["len_max"] = int(lo), int(hi or lo)
            if a.reset:
                import generator
                generator.reset_progress()
            await hunt(app, a.spec, a.n, a.min, a.recheck, a.verify, False if a.no_api else None)
        elif a.cmd == "check":
            await ensure_tg(app)
            await check_list(app, a.names)
        elif a.cmd == "info":
            await info(app, a.name)
        elif a.cmd == "market":
            await market_screen(app, a.refresh)
        elif a.cmd == "db":
            db_screen(app, a.export, a.min, a.status)
        elif a.cmd == "accounts":
            await accounts_screen(app)
        elif a.cmd == "watch":
            if a.action == "run":
                await watch_run(app)
            elif a.action == "add":
                watch_add_names(app, a.names)
            elif a.action == "rm":
                con.print(f"Удалено: {app.db.watch_remove([x.lower().lstrip('@') for x in a.names])}")
            elif a.action == "import":
                watch_import(app, a.min)
            else:
                watch_list(app)
    finally:
        await app.fr.close()
        await app.ck.close()
        app.db.c.close()
    if requested == "update":
        import updater
        updater.main([])


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1:]))
    except KeyboardInterrupt:
        con.print("\n[dim]пока 👋[/]")
