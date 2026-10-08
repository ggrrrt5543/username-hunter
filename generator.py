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


def canonical_preset(spec):
    """Accept common reversed spellings without changing custom templates."""
    return {'p5':'5p', 'p6':'6p', 'p7':'7p', 'd5':'5d', 'd6':'6d'}.get(spec.lower(), spec)


def _ranked(names, cooperative=False, min_score=0, metrics=None):
    """Return scored names, optionally yielding None as a scheduling checkpoint."""
    scored = []
    for index, name in enumerate(names, 1):
        score = rate(name).score
        scored.append((score, name))
        if metrics is not None:
            metrics['total'] = metrics.get('total', 0) + 1
            if score < min_score:
                metrics['low_score'] = metrics.get('low_score', 0) + 1
        if cooperative and index % 256 == 0:
            yield None
    scored.sort(reverse=True)
    return scored


def _full(groups, key, min_score, filt=None, chunk=20000, cooperative=False, metrics=None):
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
        if cooperative:
            yield None
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
            if cooperative and (j - i) % 512 == 511:
                PROGRESS[key][0] = j + 1  # Live view; disk checkpoint waits for the whole chunk.
                yield None
        PROGRESS[key][0] = min(N, i + chunk)
        scored = yield from _ranked(names, cooperative, min_score, metrics)
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


def candidates(spec, min_score=0, rng=random, prefix="", suffix="", lengths=(5, 12), cooperative=False, metrics=None):
    """Names only by default. cooperative=True also yields None checkpoints."""
    spec = canonical_preset(spec)
    lo, hi = lengths
    if spec.startswith("like:"):
        scored = yield from _ranked((x for x in mutations(spec[5:].strip()) if valid(x)), cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return
    if spec in EXTERNAL:
        scored = yield from _ranked({x for x in EXTERNAL[spec] if valid(x)}, cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return
    if spec == "all":
        for child in ALL_CHAIN:
            yield from candidates(child, min_score, rng, prefix, suffix, lengths, cooperative=cooperative, metrics=metrics)
        return
    if spec == "pair":
        from scorer import PREMIUM
        short = list(dict.fromkeys([w for w in list(EN)[:6000] if 2 <= len(w) <= 5] + [p for p in PREMIUM if 2 <= len(p) <= 5]))
        yield from _full([[short, short]], f"pair|{prefix}|{suffix}|{lo}-{hi}", min_score,
                         lambda u: lo <= len(u) <= hi and u.startswith(prefix) and u.endswith(suffix),
                         cooperative=cooperative, metrics=metrics)
        return
    if spec in ("b5", "b6", "b7") or spec == "brand":
        n = int(spec[1]) if spec != "brand" else None
        if n is None and lo > min(hi, 8):
            return
        seen = set()
        empty_b = 0
        while True:
            if cooperative:
                yield None
            batch = set()
            for index in range(3000):
                if cooperative and index % 128 == 127:
                    yield None
                u = markov(n or rng.randint(lo, min(hi, 8)), rng)
                if u and u not in seen and u not in EN and u not in RU and valid(prefix + u + suffix):
                    batch.add(prefix + u + suffix)
            if not batch:
                return
            seen |= batch
            scored = yield from _ranked(batch, cooperative, min_score, metrics)
            got = False
            for sc, w in scored[:500]:
                if sc >= min_score:
                    got = True
                    yield w
            empty_b = 0 if got else empty_b + 1
            if empty_b > 30:
                return
    if spec == "dict":
        scored = yield from _ranked((w for w in set(EN) | set(RU) if lo <= len(w) <= hi and valid(w)), cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return
    if spec == "niche":
        from scorer import PREMIUM
        prem = [p for p in PREMIUM if len(p) >= 2]
        digs = ["1", "7", "24", "77", "777", "99", "999", "100", "365", "01", "007", "2026", "888", "69", "420", "11", "22", "00"]
        ends = SUFFIXES + ["s", "y", "ly", "hub", "pay", "now", "zone", "land", "club", "team", "shop", "news", "bot", "app", "ai"]
        names = set()
        for index, word in enumerate(prem):
            if cooperative and index % 16 == 15:
                yield None
            names |= {word + tail for tail in ends} | {head + word for head in PREFIXES + ["x", "mr", "real", "im", "we", "top", "best"]}
            names |= {word + digit for digit in digs}
            names |= {word + other for other in prem if word != other}
            names |= {m for m in mutations(word) if len(m) >= 5}
        scored = yield from _ranked((x for x in names if lo <= len(x) <= hi and valid(x)), cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return
    if spec == "mix":
        gens = [candidates(child, min_score, rng, prefix, suffix, lengths, cooperative=cooperative, metrics=metrics)
                for child in ("brand", "dict", "combo", "5p", "6p")]
        while gens:
            for child in list(gens):
                try:
                    for _ in range(20):
                        name = next(child)
                        yield name
                        if name is None:  # An expensive child must not starve other presets.
                            break
                except StopIteration:
                    gens.remove(child)
        return
    if spec.startswith(("w", "ru")) and spec[-1].isdigit():
        n = int(re.sub(r"\D", "", spec))
        source = EN if spec.startswith("w") else RU
        scored = yield from _ranked((w for w in source if len(w) == n and valid(w)), cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return
    if spec == "combo":
        base = [w for w in list(EN)[:3000] if 3 <= len(w) <= 6]
        names = set()
        for index, word in enumerate(base):
            names |= {word + tail for tail in SUFFIXES} | {head + word for head in PREFIXES}
            if cooperative and index % 256 == 255:
                yield None
        scored = yield from _ranked((x for x in names if 5 <= len(x) <= 10 and valid(x)), cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return

    pats = PRESETS[spec][1] if spec in PRESETS else [spec]
    if prefix or suffix:
        pats = list({_fix(p, prefix.lower(), suffix.lower()) for p in pats})
    if _space(pats) <= 300_000:
        names = set()
        for index, name in enumerate(_enumerate(pats)):
            if valid(name):
                names.add(name)
            if cooperative and index % 512 == 511:
                yield None
        scored = yield from _ranked(names, cooperative, min_score, metrics)
        yield from (w for sc, w in scored if sc >= min_score)
        return
    if spec != "rep":
        groups = [[SETS.get(ch, ch.lower()) for ch in pat] for pat in sorted(pats)]
        yield from _full(groups, "pat|" + ",".join(sorted(pats)), min_score, cooperative=cooperative, metrics=metrics)
        return
    seen = set()
    empty = 0
    while True:
        if empty > 30:
            return
        if cooperative:
            yield None
        batch = set()
        for index in range(4000):
            if cooperative and index % 256 == 255:
                yield None
            pat = rng.choice(pats)
            name = "".join(rng.choice(SETS[ch]) if ch in SETS else ch.lower() for ch in pat)
            if valid(name) and name not in seen:
                if not re.search(r"(.)\1\1", name):
                    continue
                batch.add(name)
        seen |= batch
        scored = yield from _ranked(batch, cooperative, min_score, metrics)
        got = False
        for sc, name in scored[:400]:
            if sc >= min_score:
                got = True
                yield name
        empty = 0 if got else empty + 1
