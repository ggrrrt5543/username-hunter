"""Рыночные данные Fragment + оценка цены (эвристика, откалиброванная по реальным продажам)."""
import json, math, os, statistics, time
from scorer import rate

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market_cache.json")
FLOOR = {4: 2500}          # 4 буквы — только через Fragment, дорого
DEFAULT_FLOOR = 10         # на Fragment почти всё торгуется от ~10 TON


def bucket(n):
    return min(n, 9)


class Market:
    def __init__(self, fragment):
        self.fr = fragment
        self.sold, self.sale, self.auction = [], [], []
        self.ton_usd = None

    async def load(self, force=False):
        if not force and os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < 3 * 3600:
            d = json.load(open(CACHE))
            self.sold, self.sale, self.auction, self.ton_usd = d["sold"], d["sale"], d["auction"], d["ton_usd"]
            return
        self.sold = await self.fr.listings("sold", "listed")
        self.sale = await self.fr.listings("sale", "price_asc")
        self.auction = await self.fr.listings("auction", "ending")
        self.ton_usd = self.fr.ton_usd
        for lst in (self.sold, self.sale, self.auction):
            for it in lst:
                it["score"] = rate(it["username"]).score
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump({"sold": self.sold, "sale": self.sale, "auction": self.auction, "ton_usd": self.ton_usd},
                  open(CACHE, "w"))

    def heuristic(self, score, n):
        floor = FLOOR.get(n, DEFAULT_FLOOR)
        if score <= 55:
            return floor * (0.6 + 0.4 * score / 55)
        v = floor * 2 ** ((score - 55) / 9)
        if score > 80:                      # топовые слова растут в цене очень круто
            v *= 2 ** ((score - 80) / 3.5)
        return v

    def comps(self, score, n, spread=5):
        return [it["price"] for it in self.sold
                if it.get("price") and bucket(len(it["username"])) == bucket(n) and abs(it["score"] - score) <= spread]

    def estimate(self, name):
        """-> dict(low, mid, high, comps, source)"""
        sc = rate(name)
        n = len(sc.username)
        h = self.heuristic(sc.score, n)
        c = self.comps(sc.score, n)
        if len(c) >= 5 and sc.score < 80:
            med = statistics.median(c)
            mid = math.sqrt(med * h)         # геом. среднее рынка и модели
            src = f"рынок ({len(c)} похожих продаж) + модель"
        else:
            mid, src = h, "модель"
        mid = max(mid, 1)
        return {"low": mid * 0.6, "mid": mid, "high": mid * 1.8, "comps": len(c), "source": src, "score": sc}

    def stats_by_length(self):
        g = {}
        for it in self.sold:
            if it.get("price"):
                g.setdefault(bucket(len(it["username"])), []).append(it["price"])
        return {k: (len(v), statistics.median(v), sum(v) / len(v), max(v)) for k, v in sorted(g.items())}

    def deals(self, which="sale", ratio=1.5, min_score=50):
        src = self.sale if which == "sale" else self.auction
        out = []
        for it in src:
            if not it.get("price"):
                continue
            e = self.estimate(it["username"])
            r = e["mid"] / it["price"]
            if r >= ratio and e["score"].score >= min_score:
                out.append({**it, "est": e["mid"], "ratio": r, "score": e["score"].score})
        return sorted(out, key=lambda x: -x["ratio"])
