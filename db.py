"""SQLite: история проверок, чтобы не проверять одно и то же дважды."""
import os, sqlite3, time

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "hunter.db")


class DB:
    def __init__(self, path=PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.c = sqlite3.connect(path)
        self.c.execute("""CREATE TABLE IF NOT EXISTS names(
            name TEXT PRIMARY KEY, status TEXT, score INT, est REAL, price REAL,
            verified INT DEFAULT 0, checked_at REAL)""")
        self.c.execute("""CREATE TABLE IF NOT EXISTS watch(
            name TEXT PRIMARY KEY, score INT, added_at REAL, last_check REAL DEFAULT 0,
            status TEXT DEFAULT 'taken', checks INT DEFAULT 0, freed_at REAL, source TEXT)""")
        self.c.commit()

    def recent(self, name, days=7):
        r = self.c.execute("SELECT checked_at FROM names WHERE name=?", (name,)).fetchone()
        return bool(r and time.time() - r[0] < days * 86400)

    def put(self, name, status, score, est, price=None, verified=0):
        self.c.execute("INSERT OR REPLACE INTO names VALUES(?,?,?,?,?,?,?)",
                       (name, status, score, est, price, verified, time.time()))
        self.c.commit()

    def best(self, status="free", limit=50, min_score=0):
        st = status.split(",")
        q = ",".join("?" * len(st))
        return self.c.execute(f"SELECT name,status,score,est,price,verified,checked_at FROM names "
                              f"WHERE status IN ({q}) AND score>=? ORDER BY status='free' DESC, score DESC LIMIT ?",
                              (*st, min_score, limit)).fetchall()

    def counts(self):
        return dict(self.c.execute("SELECT status,COUNT(*) FROM names GROUP BY status").fetchall())

    def export(self, path, status="free,maybe"):
        import csv
        st = status.split(",")
        rows = self.c.execute("SELECT name,status,score,est,price,verified,datetime(checked_at,'unixepoch') "
                              f"FROM names WHERE status IN ({','.join('?' * len(st))}) ORDER BY score DESC", st).fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["username", "status", "score", "estimate_ton", "fragment_price", "verified", "checked_at"])
            w.writerows(rows)
        return len(rows)

    # ── уходящие юзы (watchlist) ──
    def watch_add(self, name, score, source="manual", limit=0):
        cur = self.c.execute("INSERT OR IGNORE INTO watch(name,score,added_at,source) VALUES(?,?,?,?)",
                             (name, score, time.time(), source))
        if limit:      # переполнение — выкидываем самые слабые авто-добавленные
            n = self.c.execute("SELECT COUNT(*) FROM watch").fetchone()[0]
            if n > limit:
                self.c.execute("DELETE FROM watch WHERE name IN (SELECT name FROM watch WHERE source!='manual' "
                               "ORDER BY score ASC LIMIT ?)", (n - limit,))
        self.c.commit()
        return cur.rowcount > 0

    def watch_remove(self, names):
        n = 0
        for nm in names:
            n += self.c.execute("DELETE FROM watch WHERE name=?", (nm,)).rowcount
        self.c.commit()
        return n

    def watch_list(self, limit=1000):
        return self.c.execute("SELECT name,score,added_at,last_check,status,checks,freed_at,source FROM watch "
                              "ORDER BY status IN ('free','maybe') DESC, score DESC LIMIT ?", (limit,)).fetchall()

    def watch_due(self, minutes):
        return [r[0] for r in self.c.execute("SELECT name FROM watch WHERE last_check < ? ORDER BY score DESC",
                                             (time.time() - minutes * 60,)).fetchall()]

    def watch_set(self, name, status):
        """Записать результат. -> True, если юз только что освободился."""
        r = self.c.execute("SELECT status FROM watch WHERE name=?", (name,)).fetchone()
        ok = ("free", "maybe")
        freed = bool(r and r[0] not in ok and status in ok)
        self.c.execute("UPDATE watch SET status=?, last_check=?, checks=checks+1" + (", freed_at=?" if freed else "") +
                       " WHERE name=?", (status, time.time(), *( [time.time()] if freed else []), name))
        self.c.commit()
        return freed

    def watch_count(self):
        return self.c.execute("SELECT COUNT(*), SUM(status IN ('free','maybe')) FROM watch").fetchone()

    def watch_next(self):
        r = self.c.execute("SELECT MIN(last_check) FROM watch").fetchone()
        return r[0] if r else None

    def taken_good(self, min_score, limit=500):
        return self.c.execute("SELECT name,score FROM names WHERE status='taken' AND score>=? ORDER BY score DESC LIMIT ?",
                              (min_score, limit)).fetchall()
