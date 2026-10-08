"""Search preflight regression tests. No external network or Telegram account."""
import asyncio
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rich.console import Console
import cli
import settings

class HuntPreflightTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, tg=None):
        market = SimpleNamespace(ton_usd=2, estimate=Mock(return_value={'mid':10}))
        checker = SimpleNamespace(tg=tg, fast=False, notify=AsyncMock(return_value=True),
                                  sem=SimpleNamespace(mode='auto', limit=2),
                                  check=AsyncMock(return_value=('hello', cli.MAYBE, {})))
        database = SimpleNamespace(recent=Mock(return_value=False), put=Mock(), watch_add=Mock())
        return SimpleNamespace(ck=checker, db=database, market=AsyncMock(return_value=market))

    async def run_search(self, app, candidates, choice='0', confirm=True, notify=False, n=None):
        configuration=dict(settings.DEFAULTS, preset='7', target=20, min_level='S+',
                           min_score=0, auto_relax=True, relax_ask=True, use_api=False,
                           notify_find=notify, beep=False, auto_export=False, watch_auto_add=False)
        output=io.StringIO()
        with patch.object(cli,'SET',configuration), \
             patch.object(cli,'con',Console(file=output,force_terminal=False,width=120)), \
             patch.object(cli.sys,'stdin',Mock(isatty=Mock(return_value=True))), \
             patch.object(cli,'candidates',side_effect=candidates), \
             patch.object(cli.Prompt,'ask',return_value=choice), \
             patch.object(cli.Confirm,'ask',return_value=confirm), \
             patch.dict(cli.os.environ,{},clear=True):
            await cli.hunt(app,n=n,telethon=False)
            await asyncio.sleep(0)  # Finish the mocked pause notification.
        return output.getvalue()

    async def test_unsuitable_initial_preset_can_stop_without_api(self):
        app=self.make_app()
        output=await self.run_search(app,lambda *a,**k: iter(()))
        self.assertIn('найдено 0',output)
        app.ck.check.assert_not_awaited()

    async def test_initial_pause_notification_reports_zero_found(self):
        app=self.make_app(tg=object())
        await self.run_search(app,lambda *a,**k: iter(()),notify=True)
        app.ck.notify.assert_awaited_once()
        self.assertIn('Нашёл 0',app.ck.notify.await_args.args[0])
        app.ck.check.assert_not_awaited()

    async def test_initial_preset_switch_can_continue_search(self):
        app=self.make_app()
        def candidates(spec,*args,**kwargs):
            return iter(['hello'] if spec=='mix' else [])
        output=await self.run_search(app,candidates,choice='1',n=1)
        app.ck.check.assert_awaited_once_with('hello')
        self.assertIn('1 свободных из 1 проверенных',output)
        app.db.put.assert_called_once()

if __name__=='__main__': unittest.main()
