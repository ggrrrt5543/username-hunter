"""Клиент fragment.com + t.me (публичные страницы)."""
import asyncio, re, httpx
from bs4 import BeautifulSoup

BASE = "https://fragment.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9"}


def num(text):
    m = re.search(r"\d[\d,]*\.?\d*", text or "")
    return float(m.group().replace(",", "")) if m else None


class Fragment:
    def __init__(self, concurrency=8):
        self.c = httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=False,
                                   limits=httpx.Limits(max_connections=64))
        self.limiter = None
        self.ton_usd = None

    async def close(self):
        await self.c.aclose()

    async def get(self, url, **kw):
        import time
        lim = getattr(self, "limiter", None)
        for attempt in range(4):
            try:
                t = time.time()
                r = await self.c.get(url, **kw)
                if r.status_code in (429, 502, 503, 504):
                    if lim: lim.report(ok=False, rate_limited=r.status_code == 429)
                    await asyncio.sleep(2 ** attempt)
                    continue
                if lim: lim.report(ok=True, latency=time.time() - t)
                return r
            except (httpx.TransportError, httpx.TimeoutException):
                if lim: lim.report(ok=False)
                await asyncio.sleep(1 + attempt)
        raise RuntimeError(f"не удалось загрузить {url}")

    def _rate_from(self, html):
        m = re.search(r'"tonRate":([\d.]+)', html)
        if m:
            self.ton_usd = float(m.group(1))

    async def listings(self, filt="sale", sort="price_asc", query=""):
        """filt: sale | auction | sold | '' ; sort: price_asc | price_desc | listed | ending"""
        r = await self.get(BASE, params={"query": query, "filter": filt, "sort": sort})
        self._rate_from(r.text)
        out = []
        for row in BeautifulSoup(r.text, "lxml").select("tr.tm-row-selectable"):
            a = row.select_one("a[href^='/username/']")
            v = row.select_one(".tm-value")
            if not a or not v:
                continue
            name = v.get_text(strip=True).lstrip("@")
            price = row.select_one(".icon-ton")
            st = row.select_one("[class*='tm-status']")
            t = row.select_one("time[datetime]")
            out.append({"username": name,
                        "price": num(price.get_text()) if price else None,
                        "status": st.get_text(strip=True) if st else filt,
                        "time": t["datetime"] if t else None,
                        "url": f"{BASE}/username/{name}"})
        return out

    async def username(self, name):
        """status: taken | sold | sale | auction | available | none (нет на Fragment)"""
        name = name.lower().lstrip("@")
        r = await self.get(f"{BASE}/username/{name}")
        info = {"username": name, "status": "none", "price": None, "min_bid": None,
                "history": [], "url": f"{BASE}/username/{name}"}
        if r.status_code in (301, 302):
            return info
        self._rate_from(r.text)
        soup = BeautifulSoup(r.text, "lxml")
        st = soup.select_one(".tm-section-header-status")
        txt = (st.get_text(strip=True) if st else "").lower()
        info["status"] = ("taken" if "taken" in txt else "sold" if "sold" in txt else
                          "auction" if "auction" in txt else "sale" if "sale" in txt else
                          "available" if "available" in txt else txt or "unknown")
        info["raw_status"] = st.get_text(strip=True) if st else ""
        box = soup.select_one(".tm-section-bid-info")
        if box:
            head = box.select_one("th")
            val = box.select_one(".icon-ton")
            p = num(val.get_text()) if val else None
            if head and "minimum" in head.get_text().lower():
                info["min_bid"] = p
            else:
                info["price"] = p
        for tr in soup.select(".tm-table-wrap table tbody tr"):
            cells = []
            for td in tr.select("td"):
                t = td.select_one("time[datetime]")
                w = td.select_one(".tm-wallet")
                if t:
                    cells.append(t["datetime"][:16].replace("T", " "))
                elif w:
                    h, tl = w.select_one(".head"), w.select_one(".tail")
                    cells.append(f"{h.get_text(strip=True)[:6]}…{tl.get_text(strip=True)[-4:]}" if h and tl else w.get_text(strip=True)[:14])
                else:
                    cells.append(td.get_text(" ", strip=True))
            if len(cells) >= 2:
                info["history"].append(cells)
        heads = [th.get_text(strip=True) for th in soup.select(".tm-table-wrap table thead th")]
        info["history_head"] = heads
        return info

    async def tg_taken(self, name):
        r = await self.get(f"https://t.me/{name}")
        return "tgme_page_title" in r.text
