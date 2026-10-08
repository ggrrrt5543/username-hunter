"""Оценка юзернейма 0–100: длина, словарность (EN + RU транслит), звучание, паттерны."""
import math, os, re
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    p = os.path.join(HERE, "data", name)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return {w.strip(): i + 1 for i, w in enumerate(f) if w.strip()}


EN, RU = _load("words_en.txt"), _load("words_ru.txt")
CUSTOM = _load("custom_words.txt")          # свои слова — получают топ-ранг
WORDS = {**RU, **EN, **{w: 1 for w in CUSTOM}}

PREMIUM = set("""ton btc eth nft dao defi crypto coin token wallet pay bank cash money trade swap dex bet casino
poker game games play shop store market sale news media music video film movie radio art design photo style
fashion love sex girl girls king queen god boss vip pro max top best gold diamond luxury rich star stars club
team chat bot bots ai gpt dev code app apps web cloud data tech cyber hack job jobs work travel car cars auto
food pizza coffee fit sport football soccer moscow russia dubai london paris usa china india hello world life
home city black white red blue green fire ice wolf lion tiger bear cat dog fox shark eagle apple google tesla
amazon telegram premium official support help admin info gift gifts airdrop mining miner farm stake usdt sol
doge pepe meme memes porn onlyfans escort dating vpn proxy seo smm ads crypto bitcoin dollar euro rub""".split())
VOWELS = set("aeiouy")
GOOD_BI = set("""th he in er an re on at en nd ti es or te of ed is it al ar st to nt ng se ha as ou io le ve co
me de hi ri ro ic ne ea ra ce li ch ll be ma si om ur ca el ta la ns di fo ho pe ec pr no ct us ac ot il tr ly nc
et ut ss so rs un lo wa ge ie wh ee wi em ad ol rt po we na ul ni ts mo ow pa im mi ai sh ir su id os iv ia am fi
ci vi pl ig tu ev ld ry mp fe bl ab gh ty op wo sa ay ex ke fr oo av ag if ap gr od bo sp rd do uc bu ei ov by rm
ep tt oc fa ef cu rn sc gi da yo cr cl du ga qu ue ff ba ey ls va um pp ua up lu go ht ru ug ds lt pi rc rr eg au
ck ew mu br bi pt ak pu ui rg ib tl ny ki rk ys ob mm fu ph og ms ye ud mb ip ub oi rl gu dr hr cc tw ft wn nu ku
ka zo za ze zi ix ox ax yx vo ky ko xa xo yu ju ja jo je ya ov ev zh kh""".split())
NICE_DIGITS = re.compile(r"(\d)\1{1,}|123|777|666|888|999|000|69|420|2024|2025|2026|100|1337")


@dataclass
class Score:
    username: str
    score: int
    tier: str
    parts: list = field(default_factory=list)      # [(причина, баллы)]
    words: list = field(default_factory=list)

    @property
    def reasons(self):
        return [f"{r} ({p:+})" for r, p in self.parts]


def word_rank(w):
    return WORDS.get(w)


def segment(s):
    """Лучшее разбиение на 1–2 словарных слова (по суммарной частотности)."""
    if s in WORDS:
        return [s]
    best, best_cost = None, 1e9
    for i in range(3, len(s) - 2):
        a, b = s[:i], s[i:]
        if a in WORDS and b in WORDS and all(WORDS[x] <= (3000 if len(x) == 3 else 15000) for x in (a, b)) \
                and (len(a) >= 4 or len(b) >= 4 or a in PREMIUM or b in PREMIUM):
            cost = math.log10(WORDS[a]) + math.log10(WORDS[b])
            if cost < best_cost:
                best, best_cost = [a, b], cost
    return best


def sound(s):
    """0..1 — насколько звучит как бренд."""
    letters = re.sub(r"[^a-z]", "", s)
    if len(letters) < 2:
        return 0.3
    run = worst = 0
    for ch in letters:
        run = 0 if ch in VOWELS else run + 1
        worst = max(worst, run)
    v = sum(c in VOWELS for c in letters) / len(letters)
    p = 1.0 - (0.25 * (worst - 2) if worst >= 3 else 0) - (0.3 if v < 0.2 or v > 0.7 else 0)
    bis = [letters[i:i + 2] for i in range(len(letters) - 1)]
    bq = sum(b in GOOD_BI for b in bis) / len(bis)
    rare = sum(c in "qxzj" for c in letters)
    return max(0.0, min(1.0, 0.5 * max(p, 0) + 0.5 * bq - 0.1 * rare))


def rate(username: str) -> Score:
    u = username.lower().lstrip("@").strip()
    parts, n = [], len(u)
    add = lambda r, p: parts.append((r, int(round(p))))

    core = re.sub(r"\d+$", "", u).replace("_", "")       # без хвоста цифр
    digits = re.findall(r"\d", u)
    words = segment(core) if len(core) >= 3 else None

    lb = {4: 30, 5: 20, 6: 10, 7: 4, 8: 0}.get(n, max(-25, -3 * (n - 8)))
    q = sound(core or u)
    if words is None and lb > 0:
        lb = lb * (0.35 + 0.65 * q)                       # нечитаемый набор букв стоит меньше
    add(f"длина {n}", lb)

    if words and len(words) == 1:
        r = WORDS[core]
        add(f"слово «{core}» (ранг {r})", max(18, 42 - 6 * math.log10(r)))
        if core in PREMIUM:
            add("ценная ниша", 8)
    elif words:
        r = max(WORDS[words[0]], WORDS[words[1]])
        add(f"2 слова {words[0]}+{words[1]}", max(8, 24 - 3 * math.log10(r)))
        if any(w in PREMIUM for w in words):
            add("ценная ниша", 6)
    else:
        add(f"звучание {q:.2f}", (q - 0.55) * 30)

    if digits:
        d = "".join(digits)
        pen = -7 * len(digits)
        if NICE_DIGITS.search(d) or len(set(d)) == 1:
            pen += 6
        add(f"цифры {d}", pen)
        if u[0].isalpha() and re.search(r"\d[a-z]", u):
            add("цифры в середине", -6)
    if "_" in u:
        add("подчёркивание", -18)
    if len(set(u)) == 1:
        add("одна буква", 30)
    elif re.search(r"(.)\1\1", u):
        add("тройной повтор", 6)
    if n >= 4 and u == u[::-1] and len(set(u)) > 1:
        add("палиндром", 7)

    total = 40 + sum(p for _, p in parts)
    if digits:                                    # юз с цифрами не может быть «легендарным»
        cap = 80 if NICE_DIGITS.search("".join(digits)) else 72
        if total > cap:
            add(f"потолок для юзов с цифрами ({cap})", cap - total)
            total = cap
    s = int(max(0, min(100, total)))
    return Score(u, s, level(s)[1], parts, words or [])


# Уровни юза: (мин. скор, название, грейд, цвет)
LEVELS = [
    (95, "👑 Легендарный", "S+", "bold magenta"),
    (85, "💎 Эпический", "S", "bold cyan"),
    (75, "🔥 Редкий", "A", "bold green"),
    (65, "✨ Хороший", "B", "green"),
    (50, "👍 Обычный", "C", "yellow"),
    (35, "🪨 Слабый", "D", "dark_orange"),
    (0, "🗑 Мусор", "F", "red"),
]


def level(score):
    """-> (грейд, название, цвет)"""
    for mn, name, grade, color in LEVELS:
        if score >= mn:
            return grade, name, color
    return "F", "🗑 Мусор", "red"


def level_min(grade):
    for mn, _, g, _ in LEVELS:
        if g.lower() == str(grade).lower():
            return mn
    return 0
