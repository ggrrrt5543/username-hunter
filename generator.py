"""Генерация кандидатов.
Шаблон: L буква · C согласная · V гласная · D цифра · A буква/цифра · остальное как есть.
Словарные режимы: w5 w6 w7 w8 (англ. слова), ru5 ru6 ru7 (рус. транслит), combo (слово+суффикс).
"""
import heapq, itertools, json, math, os, random, re, string
from scorer import rate, EN, RU

CONS, VOW = "bcdfghjklmnprstvwxz", "aeiouy"
SETS = {"L": string.ascii_lowercase, "C": CONS, "V": VOW, "D": string.digits,
        "A": string.ascii_lowercase + string.digits}
VALID = re.compile(r"^[a-z][a-z0-9_]{3,31}$")

PRESETS = {
    "5":   ("любые 5 букв", ["LLLLL"]),
    "6":   ("любые 6 букв", ["LLLLLL"]),
    "5p":  ("читаемые 5 букв", ["CVCVC", "VCVCV", "CVCCV", "CVVCV", "CVCVV"]),
    "6p":  ("читаемые 6 букв", ["CVCVCV", "VCVCVC", "CVCCVC", "CVCVCC", "CVVCVC"]),
    "7p":  ("читаемые 7 букв", ["CVCVCVC", "VCVCVCV", "CVCCVCV"]),
    "5d":  ("5 символов с цифрами", ["LLLLD", "LLLDD", "CVCDD", "LLDDD"]),
    "6d":  ("6 символов с цифрами", ["LLLLDD", "CVCVDD", "LLLDDD", "LLLLLD"]),
    "rep": ("с повторами букв", ["CVCCC", "CCCVC", "LLLLL"]),
    "w5":  ("англ. слова, 5 букв", None), "w6": ("англ. слова, 6 букв", None),
    "w7":  ("англ. слова, 7 букв", None), "w8": ("англ. слова, 8 букв", None),
    "ru5": ("рус. слова транслитом, 5", None), "ru6": ("рус. слова транслитом, 6", None),
    "ru7": ("рус. слова транслитом, 7", None),
    "combo": ("слово + суффикс/префикс (getx, tonapp…)", None),
    "b5":  ("🧠 брендовые 5 (нейро-подобные, звучат как слова)", None),
    "b6":  ("🧠 брендовые 6", None), "b7": ("🧠 брендовые 7", None),
    "niche": ("🪙 ниши: crypto/ton/shop/game + суффиксы, пары, цифры", None),
    "dict": ("📖 все словари (англ.+рус.) в диапазоне длины из настроек", None),
    "mix":  ("🎲 микс: брендовые + слова + комбо + читаемые", None),
    "like:слово": ("🔁 вариации слова: like:apple → appl, applee, applex, getapple…", None),
    "pair": ("🔗 все пары коротких слов (topcat, goldfox…)", None),
    "all":  ("♾  ВСЁ подряд: словари → ниши → комбо → пары → брендовые → читаемые → все буквы", None),
    "tg:канал": ("📡 парсинг канала: все @юзы и t.me-ссылки из постов (tg:durov, tg:канал+ — с вариациями)", None),
    "url:ссылка": ("🌐 парсинг любой страницы: юзы и слова с сайта", None),
    "file:путь": ("📄 юзы/слова из файла (любой текст)", None),
}
SOURCE_PREFIXES = ("tg:", "url:", "file:")
EXTERNAL = {}        # spec -> список, собранный парсером (sources.py)
ALL_CHAIN = ["dict", "niche", "combo", "pair", "b5", "b6", "b7", "5p", "6p", "7p", "5d", "6d", "5", "6"]

# ───────── прогресс полного перебора: продолжает с места остановки ─────────
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PROG_PATH = os.path.join(DATA, "progress.json")
PROGRESS = {}        # key -> [пройдено, всего]
CURRENT = [None]     # ключ перебора, который идёт сейчас


def _prog():
    try:
        return json.load(open(PROG_PATH))
    except Exception:
        return {}


def _save_prog(key, i):
    p = _prog()
    p[key] = i
    os.makedirs(DATA, exist_ok=True)
    json.dump(p, open(PROG_PATH, "w"))


def reset_progress():
    if os.path.exists(PROG_PATH):
        os.remove(PROG_PATH)


def _full(groups, key, min_score, filt=None, chunk=20000):
    """Полный перебор без повторов. groups — список вариантов, каждый — список «позиций» (наборов строк).
    Порядок перемешан (i*P mod N), так что каждый кусок — из всего пространства; лучшие в куске — первыми.
    Прогресс сохраняется: следующий запуск продолжит, где остановился."""
    sizes = [math.prod(len(d) for d in grp) for grp in groups]
    N = sum(sizes)
    if not N:
        return
    P = max(1, int(N * 0.6180339)) | 1
    while math.gcd(P, N) != 1:
        P += 2
    start = _prog().get(key, 0)
    if start >= N:                      # круг пройден — начинаем новый (проверенные недавно пропустит база)
        start = 0
    PROGRESS[key] = [start, N]
    i = start
    while i < N:
        CURRENT[0] = key
        names = set()
        for j in range(i, min(N, i + chunk)):
            k = (j * P + 7919) % N
            for grp, sz in zip(groups, sizes):
                if k < sz:
                    break
                k -= sz
            parts = []
            for d in reversed(grp):
                k, r = divmod(k, len(d))
                parts.append(d[r])
            u = "".join(reversed(parts))
            if valid(u) and (filt is None or filt(u)):
                names.add(u)
        scored = sorted(((rate(u).score, u) for u in names), reverse=True)
        for sc, u in scored:
            if sc < min_score:
                break
            yield u
        i = min(N, i + chunk)
        PROGRESS[key][0] = i
        _save_prog(key, i)
SUFFIXES = ["x", "io", "ly", "hq", "app", "bot", "ai", "go", "pro", "me", "ify", "z", "on", "er", "verse", "lab"]
PREFIXES = ["get", "my", "the", "go", "i", "try", "use", "hey"]


def valid(u):
    return bool(VALID.match(u)) and not u.endswith("_") and "__" not in u


def _space(pats):
    return sum(math.prod(len(SETS.get(ch, "x")) for ch in p) for p in pats)


def _enumerate(pats):
    for p in pats:
        for combo in itertools.product(*[SETS.get(ch, ch.lower()) for ch in p]):
            yield "".join(combo)


def _fix(p, prefix, suffix):
    if len(prefix) + len(suffix) >= len(p):
        return prefix + p[len(prefix):] if not suffix else prefix + suffix
    return prefix + p[len(prefix):len(p) - len(suffix)] + suffix


# ───────── Марковская модель: генерирует несуществующие, но «словоподобные» юзы ─────────
_MODEL = None


def _model():
    global _MODEL
    if _MODEL is None:
        from collections import defaultdict, Counter
        m = defaultdict(Counter)
        words = [w for w in list(EN)[:20000] + list(RU)[:8000] if 4 <= len(w) <= 10]
        for w in words:
            s = "^^" + w + "$"
            for i in range(len(s) - 2):
                m[s[i:i + 2]][s[i + 2]] += 1
        _MODEL = {k: (list(v), list(itertools.accumulate(v.values()))) for k, v in m.items()}
    return _MODEL


def markov(n, rng=random, tries=40):
    M = _model()
    for _ in range(tries):
        ctx, out = "^^", ""
        while len(out) < n:
            if ctx not in M:
                break
            chars, cum = M[ctx]
            c = rng.choices(chars, cum_weights=cum)[0]
            if c == "$":
                break
            out += c
            ctx = ctx[1] + c
        if len(out) == n and ctx in M and "$" in M[ctx][0]:   # слово «может так закончиться»
            return out
    return None


def mutations(word):
    """Вариации слова — то, что реально берут, когда оригинал занят."""
    w = word.lower()
    out = set()
    vow = "aeiouy"
    for s in SUFFIXES + ["s", "y", "o", "a", "us", "ix", "ex", "ia", "ium", "ism", "ers", "hub", "pay", "now"]:
        out.add(w + s)
    for p in PREFIXES + ["x", "z", "o", "u", "a", "mr", "the", "real", "its", "im", "we"]:
        out.add(p + w)
    for i in range(len(w)):
        out.add(w[:i] + w[i] + w[i:])                       # удвоить букву
        if w[i] in vow and len(w) > 4:
            out.add(w[:i] + w[i + 1:])                      # выкинуть гласную (flickr-стиль)
        for v in vow:
            if w[i] in vow and v != w[i]:
                out.add(w[:i] + v + w[i + 1:])              # заменить гласную
        if i < len(w) - 1:
            out.add(w[:i] + w[i + 1] + w[i] + w[i + 2:])    # переставить соседние
    rep = {"c": "k", "k": "c", "s": "z", "z": "s", "i": "y", "y": "i", "ph": "f", "f": "ph", "x": "ks", "ks": "x", "q": "k"}
    for a, b in rep.items():
        if a in w:
            out.add(w.replace(a, b))
    for d in ["1", "7", "77", "777", "01", "24", "69", "99", "2026", "x"]:
        out.add(w + d)
    out.discard(w)
    return out


def candidates(spec, min_score=0, rng=random, prefix="", suffix="", lengths=(5, 12)):
    """Бесконечный/конечный генератор юзов, лучшие — первыми (по батчам)."""
    lo, hi = lengths
    if spec.startswith("like:"):
        names = sorted((x for x in mutations(spec[5:].strip()) if valid(x)), key=lambda w: -rate(w).score)
        yield from (w for w in names if rate(w).score >= min_score)
        return
    if spec in EXTERNAL:                              # собранное парсером
        names = sorted({x for x in EXTERNAL[spec] if valid(x)}, key=lambda w: -rate(w).score)
        yield from (w for w in names if rate(w).score >= min_score)
        return
    if spec == "all":
        for s in ALL_CHAIN:
            yield from candidates(s, min_score, rng, prefix, suffix, lengths)
        return
    if spec == "pair":
        from scorer import PREMIUM
        short = list(dict.fromkeys([w for w in list(EN)[:6000] if 2 <= len(w) <= 5] + [p for p in PREMIUM if 2 <= len(p) <= 5]))
        yield from _full([[short, short]], f"pair|{prefix}|{suffix}|{lo}-{hi}", min_score,
                         lambda u: lo <= len(u) <= hi and u.startswith(prefix) and u.endswith(suffix))
        return
    if spec in ("b5", "b6", "b7") or spec == "brand":
        n = int(spec[1]) if spec != "brand" else None
        seen = set()
        empty_b = 0
        while True:
            batch = set()
            for _ in range(3000):
                u = markov(n or rng.randint(lo, min(hi, 8)), rng)
                if u and u not in seen and u not in EN and u not in RU and valid(prefix + u + suffix):
                    batch.add(prefix + u + suffix)
            if not batch:
                return
            seen |= batch
            got = False
            for w in sorted(batch, key=lambda w: -rate(w).score)[:500]:
                if rate(w).score >= min_score:
                    got = True
                    yield w
            empty_b = 0 if got else empty_b + 1
            if empty_b > 30:
                return
    if spec == "dict":
        words = sorted((w for w in set(EN) | set(RU) if lo <= len(w) <= hi and valid(w)), key=lambda w: -rate(w).score)
        yield from (w for w in words if rate(w).score >= min_score)
        return
    if spec == "niche":
        from scorer import PREMIUM
        prem = [p for p in PREMIUM if len(p) >= 2]
        digs = ["1", "7", "24", "77", "777", "99", "999", "100", "365", "01", "007", "2026", "888", "69", "420", "11", "22", "00"]
        ends = SUFFIXES + ["s", "y", "ly", "hub", "pay", "now", "zone", "land", "club", "team", "shop", "news", "bot", "app", "ai"]
        names = set()
        for p in prem:
            names |= {p + s for s in ends} | {x + p for x in PREFIXES + ["x", "mr", "real", "im", "we", "top", "best"]}
            names |= {p + d for d in digs}
            names |= {p + q for q in prem if p != q}
            names |= {m for m in mutations(p) if len(m) >= 5}
        names = sorted((x for x in names if lo <= len(x) <= hi and valid(x)), key=lambda w: -rate(w).score)
        yield from (w for w in names if rate(w).score >= min_score)
        return
    if spec == "mix":
        gens = [candidates(s, min_score, rng, prefix, suffix, lengths) for s in ("brand", "dict", "combo", "5p", "6p")]
        while gens:
            for gi in list(gens):
                try:
                    for _ in range(20):
                        yield next(gi)
                except StopIteration:
                    gens.remove(gi)
        return
    if spec.startswith(("w", "ru")) and spec[-1].isdigit():
        n = int(re.sub(r"\D", "", spec))
        src = EN if spec.startswith("w") else RU
        words = sorted((w for w in src if len(w) == n), key=lambda w: -rate(w).score)
        yield from (w for w in words if valid(w) and rate(w).score >= min_score)
        return
    if spec == "combo":
        base = [w for w in list(EN)[:3000] if 3 <= len(w) <= 6]
        names = {w + s for w in base for s in SUFFIXES} | {p + w for w in base for p in PREFIXES}
        names = sorted((x for x in names if 5 <= len(x) <= 10 and valid(x)), key=lambda w: -rate(w).score)
        yield from (w for w in names if rate(w).score >= min_score)
        return

    pats = PRESETS[spec][1] if spec in PRESETS else [spec]
    if prefix or suffix:                              # вшиваем начало/конец прямо в шаблон
        pats = list({_fix(p, prefix.lower(), suffix.lower()) for p in pats})
    if _space(pats) <= 300_000:                       # маленькое пространство — перебираем всё
        allc = sorted({u for u in _enumerate(pats) if valid(u)}, key=lambda w: -rate(w).score)
        yield from (w for w in allc if rate(w).score >= min_score)
        return
    if spec != "rep":                                 # большое — полный перебор кусками с сохранением прогресса
        groups = [[SETS.get(ch, ch.lower()) for ch in p] for p in sorted(pats)]
        yield from _full(groups, "pat|" + ",".join(sorted(pats)), min_score)
        return
    seen = set()
    empty = 0
    while True:                                       # rep — случайные батчи, лучшие первыми
        if empty > 30:                                # 30 батчей подряд ничего не прошло — выходим, а не висим
            return
        batch = set()
        for _ in range(4000):
            p = rng.choice(pats)
            u = "".join(rng.choice(SETS[ch]) if ch in SETS else ch.lower() for ch in p)
            if valid(u) and u not in seen:
                if spec == "rep" and not re.search(r"(.)\1\1", u):
                    continue
                batch.add(u)
        seen |= batch
        scored = sorted(batch, key=lambda w: -rate(w).score)[:400]
        got = False
        for w in scored:
            if rate(w).score >= min_score:
                got = True
                yield w
        empty = 0 if got else empty + 1
