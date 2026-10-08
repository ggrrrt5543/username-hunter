"""Search preflight regression tests. No external network or Telegram account."""
import asyncio
import io
import re
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
import generator

class HuntPreflightTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self, tg=None):
        market = SimpleNamespace(ton_usd=2, estimate=Mock(return_value={'mid':10}))
        checker = SimpleNamespace(tg=tg, fast=False, notify=AsyncMock(return_value=True),
                                  sem=SimpleNamespace(mode='auto', limit=2),
                                  check=AsyncMock(return_value=('hello', cli.MAYBE, {})))
        database = SimpleNamespace(recent=Mock(return_value=False), put=Mock(), watch_add=Mock())
        return SimpleNamespace(ck=checker, db=database, market=AsyncMock(return_value=market))

    async def run_search(self, app, candidates, choice='0', confirm=True, notify=False, n=None, preset='7', min_level='S+'):
        configuration=dict(settings.DEFAULTS, preset=preset, target=20, min_level=min_level,
                           min_score=0, auto_relax=True, relax_ask=True, use_api=False,
                           notify_find=notify, beep=False, auto_export=False, watch_auto_add=False)
        output=io.StringIO()
        with patch.object(cli,'SET',configuration), \
             patch.object(cli,'con',Console(file=output,force_terminal=False,width=120)), \
             patch.object(cli.sys,'stdin',Mock(isatty=Mock(return_value=True))), \
             patch.object(cli,'candidates',side_effect=candidates), \
             patch.object(cli.Prompt,'ask',**({'side_effect':choice} if isinstance(choice,list) else {'return_value':choice})), \
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

    async def test_failed_lowering_remembers_each_selected_level(self):
        app=self.make_app()
        output=await self.run_search(app,lambda *a,**k: iter(()),choice=['2','2','0'])
        levels=re.findall(r'сейчас: 7, уровень от .*?\((\d+)\+\)',output)
        self.assertEqual(levels,['95','85','75'])

    async def test_next_preset_keeps_lowered_level_without_duplicate_history(self):
        app=self.make_app()
        def candidates(spec,*args,**kwargs):
            return iter(['hello'] if spec=='mix' else [])
        output=await self.run_search(app,candidates,choice=['2','2','1'],n=1)
        self.assertIn('скор ≥ 75',output)
        self.assertNotIn('пробовал: 7, 7',output)
        app.ck.check.assert_awaited_once_with('hello')

    async def test_reversed_preset_spelling_is_normalized(self):
        app=self.make_app(); seen=[]
        def candidates(spec,*args,**kwargs):
            seen.append(spec)
            return iter(())
        output=await self.run_search(app,candidates,preset='p5')
        self.assertEqual(seen[0],'5p')
        self.assertIn('Пресет p5 → 5p',output)

    async def test_generation_checkpoints_allow_other_async_tasks_to_run(self):
        app=self.make_app(); pulses=[]; observed=[]
        async def ticker():
            for i in range(20):
                await asyncio.sleep(0)
                pulses.append(i)
        async def check(name):
            observed.append(len(pulses))
            return name, cli.MAYBE, {}
        app.ck.check.side_effect=check
        def candidates(spec,min_score=0,*args,**kwargs):
            if min_score==0:
                yield 'hello'; return
            for _ in range(64): yield None
            yield 'hello'
        task=asyncio.create_task(ticker())
        try:
            await self.run_search(app,candidates,n=1)
            self.assertGreater(observed[0],10)
        finally:
            await task

    async def test_small_ready_batch_is_dispatched_without_waiting_for_more_names(self):
        app=self.make_app()
        def candidates(spec,min_score=0,*args,**kwargs):
            yield 'hello'
            if min_score:
                raise AssertionError('A ready name should be checked before asking for more')
        with patch.object(cli,'GENERATION_SLICE_SECONDS',0):
            await self.run_search(app,candidates,n=1)
        app.ck.check.assert_awaited_once_with('hello')

    async def test_cached_names_are_explained_instead_of_silent_zero_checks(self):
        app=self.make_app()
        app.db.recent.return_value=True
        output=await self.run_search(app,lambda *a,**k: iter(['hello']),n=1)
        app.ck.check.assert_not_awaited()
        self.assertIn('уже проверено в базе 1',output)
        self.assertIn('уже в кэше базы: 1',output)

    async def test_actual_5p_85_reaches_checker_and_displays_nonzero_progress(self):
        app=self.make_app()
        with patch.object(generator,'_prog',return_value={}),patch.object(generator,'_save_prog'), \
             patch.object(generator,'PROGRESS',{}),patch.object(generator,'CURRENT',[None]):
            output=await asyncio.wait_for(self.run_search(app,generator.candidates,n=1,preset='5p',min_level='S'),timeout=15)
        self.assertGreater(app.ck.check.await_count,0)
        progress=re.findall(r'перебор ([\d.]+)%',output)
        self.assertTrue(progress)
        self.assertTrue(any(float(value)>0 for value in progress))
        self.assertIn('отсев по скору:',output)

if __name__=='__main__': unittest.main()
