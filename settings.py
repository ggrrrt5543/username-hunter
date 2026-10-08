"""Настройки поиска: data/settings.json + готовые профили."""
import json, os, re

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "settings.json")

# (ключ, название, тип, по умолчанию, подсказка)
SCHEMA = [
    ("— Что искать —", None, None, None, None),
    ("preset", "Пресет / шаблон", "str", "b6", "b5 b6 b7 (брендовые), mix, niche, dict, like:слово, 5p 6p, w5–w8, ru5–ru7, combo или свой (CVCVC)"),
    ("target", "Сколько найти", "int", 20, "остановиться после N свободных · 0 — без остановки (полный перебор)"),
    ("auto_relax", "Смена пресета", "bool", True, "кончился / не находит → переход на похожий пресет (5p→6p→b5…) или уровень ниже"),
    ("relax_ask", "Спрашивать перед сменой", "bool", True, "вкл — пауза и выбор: стоп / пресет ниже / уровень ниже · выкл — сам (на ночь)"),
    ("len_min", "Длина от", "int", 5, "5–32 (4 — только Fragment)"),
    ("len_max", "Длина до", "int", 12, ""),
    ("digits", "Цифры", "choice", "any", "any — любые · no — без цифр · only_end — только в конце"),
    ("underscore", "Разрешить _", "bool", False, ""),
    ("starts", "Начинается с", "str", "", "напр. ton (пусто — любое)"),
    ("ends", "Заканчивается на", "str", "", "напр. x, bot, app"),
    ("contains", "Содержит", "str", "", "через запятую — хотя бы одно"),
    ("exclude", "Не содержит", "str", "", "через запятую: xxx,qq,_"),
    ("letters_only", "Только эти буквы", "str", "", "напр. aeiounmlrst (пусто — все)"),
    ("— Ценность —", None, None, None, None),
    ("min_level", "Мин. уровень", "choice_level", "C", "S+ 👑 · S 💎 · A 🔥 · B ✨ · C 👍 · D 🪨 · F 🗑"),
    ("min_score", "Мин. скор", "int", 0, "точнее уровня: 0–100. Обычно хватит уровня, тут 0"),
    ("max_score", "Макс. скор", "int", 100, "почти всегда 100 (меньше — искать только простые)"),
    ("price_min", "Оценка от, TON", "float", 0, "искать только «дорогие» юзы"),
    ("price_max", "Оценка до, TON", "float", 0, "0 — без лимита"),
    ("only_words", "Только словарные", "bool", False, "одно или два реальных слова"),
    ("niche", "Только ценные ниши", "bool", False, "crypto, ton, shop, game, news…"),
    ("— Fragment —", None, None, None, None),
    ("show_fragment", "Показывать купить на Fragment", "bool", True, ""),
    ("frag_max", "Fragment: макс. цена, TON", "float", 500, "не показывать дороже"),
    ("deal_ratio", "Выгодный лот, если оценка ≥ цена ×", "float", 1.5, ""),
    ("deal_min_score", "Выгодный лот: мин. скор", "int", 50, ""),
    ("— Проверка —", None, None, None, None),
    ("use_api", "Проверять через Telegram API", "bool", True, "только «точно встанут»"),
    ("concurrency", "Скорость (потоки)", "speed", "auto", "auto — подбирается сама (рекомендуется) · или число 2–32"),
    ("recheck_days", "Не перепроверять N дней", "int", 7, "0 — проверять всё заново"),
    ("fast_check", "Быстрая проверка", "bool", True, "сначала t.me (1 запрос), Fragment — только если не занят. ~2× быстрее"),
    ("parse_pages", "Парсинг канала: страниц", "int", 30, "для tg:канал — сколько страниц постов листать назад (≈20 постов/стр.)"),
    ("— Уходящие юзы —", None, None, None, None),
    ("watch_auto_add", "Запоминать занятые хорошие", "bool", True, "при поиске занятые с высоким скором → в список слежки"),
    ("watch_min_score", "Слежка: мин. скор", "int", 70, "какие занятые запоминать"),
    ("watch_interval", "Слежка: перепроверка, мин", "int", 30, "как часто проверять каждый юз"),
    ("watch_max", "Слежка: макс. юзов", "int", 3000, "лишние (самые слабые авто) удаляются"),
    ("notify_tg", "Уведомлять в Telegram", "bool", True, "сообщение тебе в «Избранное», когда юз освободился"),
    ("notify_find", "Уведомлять о находках", "bool", True, "сообщение в «Избранное», когда поиск нашёл хороший юз"),
    ("notify_level", "Находки: уровень от", "choice_level", "A", "о каких находках писать: S+ · S · A · B …"),
    ("— Вывод —", None, None, None, None),
    ("show_usd", "Показывать цену в $", "bool", True, ""),
    ("beep", "Звук при находке", "bool", True, "только для 💎 топ (скор ≥ 85)"),
    ("auto_export", "Авто-экспорт в CSV", "bool", False, "data/found_ГГГГММДД.csv"),
]
FIELDS = [s for s in SCHEMA if s[1]]
DEFAULTS = {k: d for k, _, _, d, _ in FIELDS}

PROFILES = {
    "1": ("💎 Дорогие слова", {"preset": "w6", "min_score": 70, "min_level": "B", "only_words": True, "digits": "no", "price_min": 40,
                              "len_min": 5, "len_max": 8}),
    "7": ("🧠 Брендовые (лучшее качество)", {"preset": "b6", "min_score": 60, "min_level": "C", "digits": "no", "len_min": 5, "len_max": 7,
                                          "only_words": False, "niche": False, "price_min": 0}),
    "8": ("🎲 Микс всего", {"preset": "mix", "min_score": 60, "digits": "no", "len_min": 5, "len_max": 8,
                          "only_words": False, "niche": False, "price_min": 0}),
    "2": ("⚡ Короткие читаемые", {"preset": "5p", "min_score": 65, "digits": "no", "len_min": 5, "len_max": 5,
                                  "only_words": False, "price_min": 0}),
    "3": ("🇷🇺 Русские слова", {"preset": "ru6", "min_score": 65, "only_words": True, "digits": "no",
                               "len_min": 5, "len_max": 8}),
    "4": ("🪙 Крипто-ниша", {"preset": "niche", "niche": True, "min_score": 55, "digits": "no", "len_max": 10}),
    "5": ("🔢 Красивые с цифрами", {"preset": "6d", "digits": "only_end", "min_score": 55, "len_min": 5, "len_max": 7}),
    "6": ("💰 Дешёвые лоты для перепродажи", {"frag_max": 30, "deal_ratio": 1.8, "deal_min_score": 60, "show_fragment": True}),
}


def load():
    s = dict(DEFAULTS)
    if os.path.exists(PATH):
        try:
            s.update({k: v for k, v in json.load(open(PATH, encoding="utf-8")).items() if k in DEFAULTS})
            if s.get("concurrency") == 8:      # старое значение по умолчанию → авто
                s["concurrency"] = "auto"
        except Exception:
            pass
    return s


def save(s):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(s, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def parse(kind, raw):
    raw = raw.strip()
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw.replace(",", "."))
    if kind == "bool":
        return raw.lower() in ("1", "y", "yes", "да", "д", "+", "true", "on", "вкл")
    if kind == "speed":
        if raw.lower() in ("auto", "авто", "a", "0", ""):
            return "auto"
        v = int(raw)
        if not 1 <= v <= 32:
            raise ValueError("auto или число 1–32")
        return v
    if kind == "choice_level":
        v = raw.upper()
        if v not in ("S+", "S", "A", "B", "C", "D", "F"):
            raise ValueError("S+, S, A, B, C, D или F")
        return v
    if kind == "choice":
        if raw not in ("any", "no", "only_end"):
            raise ValueError("any / no / only_end")
        return raw
    return raw.lower()


def _list(v):
    return [x.strip().lower() for x in str(v).split(",") if x.strip()]


def name_ok(u, s):
    """Быстрые фильтры по самому юзу (до проверки)."""
    if not (s["len_min"] <= len(u) <= s["len_max"]):
        return False
    has_d = any(c.isdigit() for c in u)
    if s["digits"] == "no" and has_d:
        return False
    if s["digits"] == "only_end" and has_d and not re.fullmatch(r"[a-z_]+\d+", u):
        return False
    if not s["underscore"] and "_" in u:
        return False
    if s["starts"] and not u.startswith(s["starts"]):
        return False
    if s["ends"] and not u.endswith(s["ends"]):
        return False
    inc = _list(s["contains"])
    if inc and not any(x in u for x in inc):
        return False
    if any(x in u for x in _list(s["exclude"])):
        return False
    if s["letters_only"] and any(c.isalpha() and c not in s["letters_only"] for c in u):
        return False
    return True


def value_ok(sc, est, s):
    """Фильтры по ценности (скор, оценка, словарность, ниша)."""
    from scorer import PREMIUM, level_min
    if sc.score < level_min(s.get("min_level", "F")):
        return False
    if not (s["min_score"] <= sc.score <= s["max_score"]):
        return False
    if est < s["price_min"] or (s["price_max"] and est > s["price_max"]):
        return False
    if s["only_words"] and not sc.words:
        return False
    if s["niche"] and not any(w in PREMIUM for w in sc.words):
        return False
    return True
