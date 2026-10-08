"""Авто-скорость: сам подбирает число параллельных запросов (AIMD, как TCP).
Всё ок и сайт отвечает быстро → +1 поток. Лимит/ошибка/тормоза → режем вдвое."""
import asyncio, time


class AutoLimiter:
    def __init__(self, start=8, lo=2, hi=40, fixed=None):
        self.fixed = fixed
        self.limit = fixed or start
        self.lo, self.hi = lo, hi
        self.active = 0
        self.cond = asyncio.Condition()
        self.ok_streak = 0
        self.lat = None              # сглаженная задержка ответа, сек
        self.base_lat = None
        self.events = 0
        self.last_cut = 0.0

    async def __aenter__(self):
        async with self.cond:
            await self.cond.wait_for(lambda: self.active < int(self.limit))
            self.active += 1
        return self

    async def __aexit__(self, *a):
        async with self.cond:
            self.active -= 1
            self.cond.notify_all()

    def report(self, ok=True, latency=None, rate_limited=False):
        if self.fixed:
            return
        self.events += 1
        if latency is not None:
            self.lat = latency if self.lat is None else 0.85 * self.lat + 0.15 * latency
            if self.base_lat is None or latency < self.base_lat:
                self.base_lat = max(latency, 0.05)
        now = time.time()
        slow = self.lat and self.base_lat and self.lat > self.base_lat * 4 and self.lat > 1.5
        if rate_limited or not ok or slow:
            if now - self.last_cut > 3:          # не режем чаще раза в 3 сек
                self.limit = max(self.lo, self.limit / 2)
                self.last_cut = now
            self.ok_streak = 0
            return
        self.ok_streak += 1
        if self.ok_streak >= max(4, int(self.limit)):   # серия удачных → +1 поток
            self.limit = min(self.hi, self.limit + 1)
            self.ok_streak = 0

    @property
    def mode(self):
        return "ручная" if self.fixed else "авто"
