"""Проверка доступности: Fragment -> t.me -> Telegram API (пул аккаунтов)."""
import asyncio, glob, json, logging, os, shutil, time

# статусы
FREE, MAYBE, TAKEN, FRAG_SALE, FRAG_AVAIL, FRAG_SOLD, INVALID, ERROR = (
    "free", "maybe", "taken", "on_sale", "fragment", "nft", "invalid", "error")
LABEL = {FREE: "🟢 свободен ✓", MAYBE: "🟡 похоже свободен", TAKEN: "🔴 занят", FRAG_SALE: "💰 продаётся", FRAG_AVAIL: "💎 аукцион Fragment",
         FRAG_SOLD: "🟣 NFT (у владельца)", INVALID: "⚪ некорректное (TG не даст)", ERROR: "❓ ошибка"}

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SESS = os.path.join(DATA, "sessions")
COOL_PATH = os.path.join(SESS, "cooldown.json")
MAX_WAIT = 90          # если все аккаунты в флуде дольше — не ждём, проверяем по сайтам (🟡)


class Account:
    """Один аккаунт Telegram: свой клиент, своя очередь, своя пауза и свой флуд-лимит."""
    def __init__(self, name, client):
        self.name, self.client = name, client
        self.lock = asyncio.Lock()
        self.delay = 1.0
        self.cool = 0.0          # до какого времени отдыхает после FloodWait
        self.checks = 0
        self.waiters = 0
        self.title = name
        self.dead = False

    @property
    def state(self):
        if self.dead:
            return "❌ отключён"
        left = self.cool - time.time()
        return f"⏳ флуд {int(left)}с" if left > 0 else "✅ работает"


def make_client(path):
    from telethon import TelegramClient, connection
    kw = {"connection_retries": 5, "retry_delay": 2, "timeout": 15}
    proxy = os.getenv("PROXY", "").strip()      # socks5://user:pass@host:port  или  mtproxy://secret@host:port
    if proxy.startswith("mtproxy://"):
        secret, _, hp = proxy[10:].partition("@")
        host, _, port = hp.partition(":")
        kw.update(connection=connection.ConnectionTcpMTProxyRandomizedIntermediate, proxy=(host, int(port), secret))
    elif proxy:
        from urllib.parse import urlparse
        u = urlparse(proxy)
        kw["proxy"] = {"proxy_type": u.scheme.replace("socks5h", "socks5"), "addr": u.hostname, "port": u.port,
                       "username": u.username, "password": u.password, "rdns": True}
        kw["connection"] = connection.ConnectionTcpObfuscated
    else:
        kw["connection"] = connection.ConnectionTcpObfuscated   # маскировка трафика — помогает при блокировках
    return TelegramClient(path, int(os.getenv("API_ID")), os.getenv("API_HASH"), **kw)


def _net_hint(e, log):
    if "0 bytes read" in str(e) or "closed the connection" in str(e).lower() or "timeout" in str(e).lower():
        log("[yellow]Провайдер режет подключение к Telegram. Включи VPN (на весь ПК) и запусти снова, "
            "или пропиши прокси в .env: PROXY=socks5://127.0.0.1:1080 или PROXY=mtproxy://secret@host:port[/]")


def session_names():
    os.makedirs(SESS, exist_ok=True)
    old = os.path.join(DATA, "checker.session")          # перенос старой сессии (v1–v6)
    if os.path.exists(old) and not os.path.exists(os.path.join(SESS, "main.session")):
        shutil.move(old, os.path.join(SESS, "main.session"))
    names = sorted(os.path.basename(p)[:-8] for p in glob.glob(os.path.join(SESS, "*.session")))
    return sorted(names, key=lambda n: (n != "main", n))


class Checker:
    def __init__(self, fragment, concurrency=8):
        self.fr = fragment
        from limiter import AutoLimiter
        self.sem = AutoLimiter(start=8, fixed=None if concurrency in (0, "auto", None) else int(concurrency))
        fragment.limiter = self.sem
        self.accounts = []
        self.cool_saved = self._load_cool()
        self.fast = True            # сначала t.me (1 запрос); Fragment — только если t.me не видит владельца

    def _load_cool(self):
        try:
            return json.load(open(COOL_PATH))
        except Exception:
            return {}

    def _save_cool(self):
        try:
            os.makedirs(SESS, exist_ok=True)
            json.dump({a.name: a.cool for a in self.accounts if a.cool > time.time()}, open(COOL_PATH, "w"))
        except Exception:
            pass

    @property
    def api_paused_until(self):
        """Время, до которого API недоступен (все аккаунты в флуде дольше MAX_WAIT), иначе 0."""
        live = [a for a in self.accounts if not a.dead]
        if not live:
            return 0
        t = min(a.cool for a in live)
        return t if t - time.time() > MAX_WAIT else 0

    # совместимость: первый живой клиент, средняя пауза, всего проверок
    @property
    def tg(self):
        live = [a for a in self.accounts if not a.dead]
        return live[0].client if live else None

    @property
    def delay(self):
        live = [a for a in self.accounts if not a.dead]
        return sum(a.delay for a in live) / len(live) if live else 0.0

    @property
    def api_checks(self):
        return sum(a.checks for a in self.accounts)

    async def _open(self, name, log, interactive=False):
        client = make_client(os.path.join(SESS, name))
        await client.connect()
        if not await client.is_user_authorized():
            if not interactive:
                await client.disconnect()
                log(f"[yellow]Аккаунт «{name}» не авторизован — пропускаю (удали его в меню «Аккаунты» или добавь заново)[/]")
                return None
            await client.start()                # номер телефона + код из Telegram
        acc = Account(name, client)
        try:
            me = await client.get_me()
            acc.title = f"{me.first_name or ''} {('@' + me.username) if me.username else ''}".strip()
            acc.uid = me.id
        except Exception:
            acc.uid = None
        return acc

    async def start_telethon(self, log=print):
        if not (os.getenv("API_ID") and os.getenv("API_HASH")):
            log("API_ID/API_HASH не заданы в .env — Telethon выключен")
            return False
        names = session_names() or ["main"]
        for nm in names:
            if any(a.name == nm for a in self.accounts):
                continue
            try:
                acc = await self._open(nm, log, interactive=(nm == names[0] and not self.accounts))
                if acc:
                    acc.cool = float(self.cool_saved.get(nm, 0))     # флуд-лимит переживает перезапуск
                    self.accounts.append(acc)
            except Exception as e:
                log(f"[red]Аккаунт «{nm}»: не удалось подключиться к Telegram: {e}[/]")
                _net_hint(e, log)
        return bool(self.accounts)

    async def add_account(self, phone_cb, code_cb, pass_cb, log=print):
        """Добавить ещё один аккаунт: номер + код (+ пароль 2FA). -> Account | None"""
        os.makedirs(SESS, exist_ok=True)
        i = 2
        while os.path.exists(os.path.join(SESS, f"acc{i}.session")):
            i += 1
        name = f"acc{i}"
        client = make_client(os.path.join(SESS, name))
        try:
            await client.start(phone=phone_cb, code_callback=code_cb, password=pass_cb)
            me = await client.get_me()
        except Exception as e:
            log(f"[red]Не получилось войти: {e}[/]")
            _net_hint(e, log)
            try:
                await client.disconnect()
            except Exception:
                pass
            p = os.path.join(SESS, name + ".session")
            if os.path.exists(p):
                os.remove(p)
            return None
        if any(getattr(a, "uid", None) == me.id for a in self.accounts):
            log("[yellow]Этот аккаунт уже добавлен[/]")
            await client.log_out()
            return None
        acc = Account(name, client)
        acc.uid = me.id
        acc.title = f"{me.first_name or ''} {('@' + me.username) if me.username else ''}".strip()
        self.accounts.append(acc)
        return acc

    async def remove_account(self, acc, logout=True):
        self.accounts.remove(acc)
        try:
            if logout:
                await acc.client.log_out()          # завершает сеанс в TG и удаляет файл
            else:
                await acc.client.disconnect()
        except Exception:
            pass
        p = os.path.join(SESS, acc.name + ".session")
        if os.path.exists(p):
            os.remove(p)

    async def close(self):
        for a in self.accounts:
            try:
                await a.client.disconnect()
            except Exception:
                pass

    async def notify(self, text):
        """Сообщение себе в «Избранное» (первым аккаунтом)."""
        if not self.tg:
            return False
        try:
            await self.tg.send_message("me", text)
            return True
        except Exception as e:
            logging.warning("notify: %s", e)
            return False

    async def _pick(self):
        """Свободный аккаунт: не занят, не в флуд-лимите; если все заняты — с самой короткой очередью."""
        while True:
            live = [a for a in self.accounts if not a.dead]
            if not live:
                return None
            now = time.time()
            ready = [a for a in live if a.cool <= now]
            if not ready:
                if min(a.cool for a in live) - now > MAX_WAIT:
                    return None                     # долгий флуд — не висим
                await asyncio.sleep(min(5.0, max(0.2, min(a.cool for a in live) - now)))
                continue
            idle = [a for a in ready if not a.lock.locked()]
            return min(idle or ready, key=lambda a: (a.waiters, a.checks))

    async def telethon_check(self, name):
        from telethon import functions, errors
        for attempt in range(6):
            acc = await self._pick()
            if acc is None:
                return MAYBE if self.accounts else ERROR      # API на паузе → «похоже свободен», перепроверить позже
            acc.waiters += 1
            try:
                async with acc.lock:
                    if acc.cool > time.time():
                        continue                    # пока ждали — словил флуд, берём другой
                    tg = acc.client
                    try:
                        if not tg.is_connected():
                            await tg.connect()
                        ok = await tg(functions.account.CheckUsernameRequest(username=name))
                        acc.checks += 1
                        acc.delay = max(0.8, acc.delay * 0.97)       # всё ок — чуть быстрее
                        await asyncio.sleep(acc.delay)
                        return FREE if ok else TAKEN
                    except errors.FloodWaitError as e:
                        logging.warning("FloodWait %s: %ss", acc.name, e.seconds)
                        acc.delay = min(3.0, acc.delay * 1.6 + 0.3)  # лимит — этот аккаунт отдыхает, остальные работают
                        acc.cool = time.time() + e.seconds + 1
                        self._save_cool()
                    except errors.UsernamePurchaseAvailableError:
                        await asyncio.sleep(acc.delay)
                        return FRAG_AVAIL
                    except errors.UsernameInvalidError:       # «Некорректное имя пользователя» в TG
                        await asyncio.sleep(acc.delay)
                        return INVALID
                    except errors.UsernameOccupiedError:
                        await asyncio.sleep(acc.delay)
                        return TAKEN
                    except (errors.AuthKeyUnregisteredError, errors.UserDeactivatedError,
                            errors.UserDeactivatedBanError, errors.SessionRevokedError) as e:
                        logging.warning("аккаунт %s отключён: %s", acc.name, e)
                        acc.dead = True
                    except errors.RPCError as e:
                        logging.warning("telethon %s: %s", name, e)
                        await asyncio.sleep(acc.delay)
                        return ERROR
                    except (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError) as e:
                        logging.warning("переподключение %s: %s", acc.name, e)   # обрыв — переподключаемся
                        await asyncio.sleep(2 + attempt * 2)
                        try:
                            await tg.disconnect()
                            await tg.connect()
                        except Exception:
                            pass
            finally:
                acc.waiters -= 1
        return ERROR

    async def web(self, name, full=False):
        """Только сайты (Fragment + t.me). -> (status|None, info); None — сайт не видит владельца."""
        async with self.sem:
            try:
                if self.fast and not full and await self.fr.tg_taken(name):
                    return TAKEN, {"username": name, "status": "taken"}
                info = await self.fr.username(name)
                st = info["status"]
                if st == "taken":
                    return TAKEN, info
                if st in ("sale", "auction"):
                    return FRAG_SALE, info
                if st == "available":
                    return FRAG_AVAIL, info
                if st == "sold":
                    return FRAG_SOLD, info
                if (full or not self.fast) and await self.fr.tg_taken(name):
                    return TAKEN, info
                return None, info
            except Exception as e:
                logging.debug("check %s: %s", name, e)
                return ERROR, {}

    async def check(self, name, full=False):
        """-> (name, status, info). Сначала сайты; API — только если сайт не видит владельца."""
        st, info = await self.web(name, full)
        if st is not None:
            return name, st, info
        if self.tg:
            return name, await self.telethon_check(name), info
        return name, MAYBE, info
