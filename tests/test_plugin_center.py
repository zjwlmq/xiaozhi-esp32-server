from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import asyncio
import base64
import json
import socket
import queue
import threading
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'main/xiaozhi-server'))
from core.plugins.context_plugins import holiday_context, in_quiet_hours, optimize_memory
from core.plugins.settings import normalize, defaults
from core.plugins.runtime import PluginRuntime
from core.plugins.image_generation import generate_image, resolve_endpoint
from core.utils.dialogue import Dialogue, Message


def states(*enabled):
    result = {pid: {'enabled': True, 'settings': {}} for pid in enabled}
    if any(pid in enabled for pid in ('holiday-awareness', 'proactive-messaging')):
        result.setdefault('time-awareness', {'enabled': True, 'settings': {}})
    return result


class SettingsTests(unittest.TestCase):
    def test_catalogs_are_identical_for_server_and_console(self):
        a = ROOT/'main/xiaozhi-server/core/plugins/catalog.json'
        b = ROOT/'main/manager-api/src/main/resources/plugin-center/catalog.json'
        self.assertEqual(json.loads(a.read_text(encoding='utf-8')), json.loads(b.read_text(encoding='utf-8')))

    def test_dependencies_required_without_enabling_unrelated_plugins(self):
        with self.assertRaises(ValueError): normalize({'holiday-awareness': {'enabled': True}})
        result = normalize(states('holiday-awareness'))
        self.assertEqual(set(result), {'time-awareness', 'holiday-awareness'})

    def test_wrong_types_unknown_keys_and_unsafe_urls_rejected(self):
        for payload in [
            {'time-awareness': {'enabled': 'false'}},
            {'memory-optimizer': {'settings': {'max_characters': True}}},
            {'image-generation': {'settings': {'endpoint': 'file:///etc/passwd'}}},
            {'image-generation': {'settings': {'endpoint': 'https://secret@example.test/images'}}},
            {'image-generation': {'settings': {'shell': 'something'}}},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ValueError): normalize(payload)

    def test_calendar_requires_explicit_workday_boolean(self):
        with self.assertRaises(ValueError): normalize({'holiday-awareness': {'settings': {'calendar': [{'date': '2027-01-01', 'is_day_off': 'yes'}]}}})

    def test_holiday_does_not_imply_day_off(self):
        now = datetime.fromisoformat('2027-01-01T09:00:00+08:00')
        result = holiday_context(now, {'lookahead_days': 0, 'calendar': []})
        self.assertIn('元旦', result['days'][0]['festivals'])
        self.assertIsNone(result['days'][0]['is_day_off'])
        configured = holiday_context(now, {'lookahead_days': 0, 'calendar': [{'date':'2027-01-01','name':'个人排班','is_day_off':False}]})
        self.assertFalse(configured['days'][0]['is_day_off'])

    def test_lunar_festival_uses_pinned_library(self):
        result = holiday_context(datetime.fromisoformat('2025-01-29T09:00:00+08:00'), {'lookahead_days':0, 'calendar':[]})
        self.assertTrue(result['lunar_calendar_available'])
        self.assertIn('春节', result['days'][0]['festivals'])

    def test_quiet_hours_cross_midnight_and_end_boundary(self):
        for hour in (23, 0, 7): self.assertTrue(in_quiet_hours(datetime(2026,11,1,hour), '22:00','08:00'))
        self.assertFalse(in_quiet_hours(datetime(2026,11,1,8), '22:00','08:00'))

    def test_memory_keeps_negation_dates_and_relevance(self):
        source = '2024-02-21 备份任务没有完成\n2024-02-21 备份任务没有完成\n' + ('无关材料。'*200) + '\n2026-03-01 演示项目正在迁移数据库'
        result = optimize_memory(source, '数据库和备份', {'max_characters':500,'deduplicate':True})
        self.assertIn('2024-02-21 备份任务没有完成', result)
        self.assertEqual(result.count('备份任务没有完成'), 1)
        self.assertIn('2026-03-01 演示项目正在迁移数据库', result)
        self.assertLessEqual(len(result), 500)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plugin-center-test-')
        self.now = datetime.fromisoformat('2026-11-01T10:00:00+08:00')
        self.dialogue = Dialogue()
        self.dialogue.put(Message(role='system', content='时间{{current_date}} {{current_time}}\n<memory></memory>'))
        self.sent = []
        async def send(text): self.sent.append(text)
        self.conn = SimpleNamespace(config={}, device_id='device-1', dialogue=self.dialogue,
            features={'plugin_images':True}, intent_type='function_call', memory=object(),
            websocket=SimpleNamespace(send=AsyncMock()), session_id='session',
            llm=SimpleNamespace(response=lambda *_: iter(['现在方便聊两句吗？'])), plugin_send_text=send,
            client_is_speaking=False, client_have_voice=False)
        self.runtime = PluginRuntime(self.conn, Path(self.temp.name)/'live.sqlite3', clock=lambda:self.now)
        self.dialogue.plugin_runtime = self.runtime
        self.conn.plugin_runtime = self.runtime

    async def asyncTearDown(self):
        await self.runtime.close()
        assert Path(self.temp.name).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        self.temp.cleanup()

    def enable(self, *ids): self.runtime.apply_config({'revision':1,'scope':'owner:agent:device-1','plugins':states(*ids)})

    async def test_prompt_changes_only_for_enabled_plugin_and_refreshes_midnight(self):
        self.runtime.begin_turn('u1')
        self.assertNotIn('<time_context>', self.dialogue.get_llm_dialogue_with_memory()[0]['content'])
        self.enable('time-awareness')
        self.now = datetime.fromisoformat('2026-11-01T23:58:00+08:00')
        self.runtime.begin_turn('u2')
        self.now += timedelta(minutes=5)
        self.runtime.begin_turn('u3')
        prompt = self.dialogue.get_llm_dialogue_with_memory(r'C:\Users\test\notes')[0]['content']
        self.assertIn('2026-11-02 00:03', prompt)
        self.assertIn('"elapsed_since_previous_interaction_seconds": 300.0', prompt)
        self.assertIn(r'C:\Users\test\notes', prompt)
        self.runtime.apply_config({'revision':2,'plugins':{}})
        self.assertNotIn('<time_context>', self.dialogue.get_llm_dialogue_with_memory()[0]['content'])

    async def test_persistence_and_scopes_do_not_leak(self):
        self.enable('time-awareness')
        self.runtime.begin_turn('u1')
        self.now += timedelta(minutes=2)
        self.runtime.record_sent('r1')
        self.now += timedelta(hours=4)
        reopened = PluginRuntime(self.conn, Path(self.temp.name)/'live.sqlite3', clock=lambda:self.now)
        reopened.apply_config({'plugins':states('time-awareness'),'scope':'owner:agent:device-1'})
        reopened.begin_turn('u2')
        context = reopened.store.for_turn(reopened.scope, 'u2')
        self.assertEqual(context['elapsed_since_previous_interaction_seconds'],14400)
        reopened.apply_config({'plugins':states('time-awareness'),'scope':'other:agent:device-1'})
        reopened.begin_turn('u1')
        self.assertTrue(reopened.store.for_turn(reopened.scope,'u1')['first_recorded_live_interaction'])
        await reopened.close()

    async def test_lunar_placeholder_follows_selected_timezone_at_day_boundary(self):
        self.now=datetime.fromisoformat('2025-01-28T16:30:00+00:00')
        self.enable('time-awareness')
        self.dialogue.dialogue[0].content='日期{{current_date}} 农历{{current_lunar_date}}'
        self.runtime.begin_turn('new-year')
        prompt=self.dialogue.get_llm_dialogue_with_memory()[0]['content']
        self.assertIn('2025-01-29',prompt)
        self.assertIn('正月初一',prompt)
        self.assertNotIn('农历获取失败',prompt)
        self.runtime.apply_config({'plugins':{'time-awareness':{'enabled':True,'settings':{'timezone':'UTC'}}}})
        self.runtime.begin_turn('utc-day')
        self.assertTrue(self.dialogue.get_llm_dialogue_with_memory()[0]['content'].startswith('日期2025-01-28'))

    async def test_memory_paths_and_backslashes_are_preserved_in_model_prompt(self):
        memory=r'项目在 C:\repo\test，标记 \1 仍未完成'
        self.assertIn(memory,self.dialogue.get_llm_dialogue_with_memory(memory)[0]['content'])

    async def test_proactive_has_no_first_contact_or_disabled_send(self):
        self.enable('proactive-messaging')
        await self.runtime.tick()
        self.assertEqual(self.sent, [])
        self.runtime.begin_turn('u1'); self.now += timedelta(hours=3)
        self.runtime.apply_config({'plugins':{}})
        await self.runtime.tick()
        self.assertEqual(self.sent, [])

    async def test_proactive_caps_and_quiet_hours_survive_restart(self):
        self.enable('proactive-messaging')
        self.runtime.begin_turn('u1')
        for _ in range(3): self.now += timedelta(hours=3); await self.runtime.tick()
        self.assertEqual(len(self.sent),2)
        self.now = datetime.fromisoformat('2026-11-01T23:00:00+08:00')
        await self.runtime.tick()
        self.assertEqual(len(self.sent),2)
        reopened = PluginRuntime(self.conn, Path(self.temp.name)/'live.sqlite3', clock=lambda:self.now)
        reopened.apply_config({'plugins':states('proactive-messaging'),'scope':self.runtime.scope})
        await reopened.tick()
        self.assertEqual(len(self.sent),2)
        await reopened.close()

    async def test_user_arrives_while_proactive_generation_is_cancelled(self):
        self.enable('proactive-messaging')
        self.runtime.begin_turn('u1'); self.now += timedelta(hours=3)
        def response(*_):
            self.runtime.begin_turn('new-user-event')
            yield '已经过时的主动消息'
        self.conn.llm.response=response
        await self.runtime.tick()
        self.assertEqual(self.sent, [])

    async def test_turning_off_while_generating_prevents_delivery(self):
        self.enable('proactive-messaging')
        self.runtime.begin_turn('u1'); self.now += timedelta(hours=3)
        def response(*_):
            self.runtime.apply_config({'plugins':{}})
            yield '不能发送'
        self.conn.llm.response=response
        await self.runtime.tick()
        self.assertEqual(self.sent, [])

    async def test_skip_not_flooded_by_scheduler(self):
        self.enable('proactive-messaging'); self.runtime.begin_turn('u1')
        self.now += timedelta(hours=3)
        called=[]
        self.conn.llm.response=lambda *_: (called.append(1) or iter(['[SKIP]']))
        await self.runtime.tick(); await self.runtime.tick()
        self.assertEqual(len(called),1)
        self.assertEqual(self.sent,[])

    async def test_close_cancels_watch_task(self):
        await self.runtime.start()
        task=self.runtime.task
        await asyncio.sleep(0)
        await self.runtime.close()
        self.assertTrue(task.done())

    async def test_memory_failure_does_not_disable_time(self):
        self.enable('time-awareness','memory-optimizer'); self.runtime.begin_turn('u1')
        with patch('core.plugins.runtime.optimize_memory',side_effect=RuntimeError('private-secret')):
            self.assertEqual(self.runtime.prepare_memory('原始记忆','问题'),'原始记忆')
        self.assertIn('<time_context>',self.runtime.augment_prompt('人格'))
        self.assertNotIn('private-secret',json.dumps(self.runtime.snapshot()))

    async def test_image_capability_is_checked_and_disabled_execution_is_blocked(self):
        config=states('image-generation')
        config['image-generation']['settings']={'endpoint':'https://images.example.test/v1/images/generations','api_key':'test-only-key','model':'test-model'}
        self.runtime.apply_config({'plugins':config})
        self.assertTrue(self.runtime.image_tool_ready())
        self.conn.features={}
        self.assertFalse(self.runtime.image_tool_ready())
        with self.assertRaises(ValueError): await self.runtime.execute_image('一只小狗')
        self.conn.websocket.send.assert_not_awaited()

    async def test_generated_image_is_delivered_with_origin_and_failures_are_retryable(self):
        config=states('image-generation')
        config['image-generation']['settings']={'endpoint':'https://images.example.test/v1/images/generations','api_key':'test-only-key','model':'test-model'}
        self.runtime.apply_config({'plugins':config})
        with patch('core.plugins.runtime.generate_image',side_effect=RuntimeError('secret')):
            with self.assertRaises(RuntimeError): await self.runtime.execute_image('图片')
        self.assertTrue(self.runtime.image_tool_ready())
        with patch('core.plugins.runtime.generate_image',new=AsyncMock(return_value={'url':'https://images.example.test/a.png'})):
            result=await self.runtime.execute_image('图片')
        self.assertEqual(result['status'],'sent')
        delivered=json.loads(self.conn.websocket.send.await_args.args[0])
        self.assertEqual(delivered['type'],'plugin_image')
        self.assertEqual(delivered['origin'],'generated')
        self.assertEqual(self.runtime.status('image-generation')[0],'ready')

    async def test_image_http_protocol_and_bad_payload(self):
        import httpx
        received=[]
        def respond(request):
            received.append(json.loads(request.content))
            self.assertEqual(request.url.host, '93.184.216.34')
            self.assertEqual(request.headers['host'], 'images.example.test')
            self.assertEqual(request.extensions['sni_hostname'], 'images.example.test')
            return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()}]})
        settings={'endpoint':'https://images.example.test/v1/images/generations','api_key':'test-only-key','model':'test','size':'1024x1024'}
        dns=[(socket.AF_INET,socket.SOCK_STREAM,socket.IPPROTO_TCP,'',('93.184.216.34',443))]
        with patch('socket.getaddrinfo',return_value=dns):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                result=await generate_image(settings,'画一张图',client)
        self.assertTrue(result['url'].startswith('data:image/png;base64,'))
        self.assertEqual(received[0]['n'],1)
        with patch('socket.getaddrinfo',return_value=dns):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'data':[{'url':'javascript:alert(1)'}]}))) as client:
                with self.assertRaises(ValueError): await generate_image(settings,'图片',client)

    async def test_image_tool_result_can_be_used_as_a_model_tool_message(self):
        from loguru import logger
        with patch.dict(sys.modules, {'config.logger': SimpleNamespace(setup_logging=lambda:logger)}):
            from core.plugins.tool_executor import PluginCenterExecutor
            from plugins_func.register import Action
        executor=PluginCenterExecutor(self.conn)
        with patch.object(self.runtime,'image_tool_ready',return_value=True), patch.object(
                self.runtime,'execute_image',new=AsyncMock(return_value={'status':'sent','origin':'generated'})):
            result=await executor.execute(self.conn,'generate_companion_image',{'prompt':'图片'})
        self.assertEqual(result.action,Action.REQLLM)
        self.dialogue.put(Message(role='tool',tool_call_id='call-1',content=result.result))
        message=self.dialogue.get_llm_dialogue_with_memory()[-1]
        self.assertIsInstance(message['content'],str)
        self.assertEqual(json.loads(message['content'])['status'],'sent')

    async def test_proactive_uses_normal_tts_queue_and_records_actual_delivery(self):
        from core.providers.tts.dto.dto import SentenceType
        self.enable('proactive-messaging')
        self.runtime.begin_turn('before-idle')
        self.now+=timedelta(hours=3)
        del self.conn.plugin_send_text
        self.conn.tts=SimpleNamespace(tts_text_queue=queue.Queue())
        start=AsyncMock()
        with patch.dict(sys.modules, {'core.handle.sendAudioHandle':SimpleNamespace(send_tts_message=start)}):
            await self.runtime.tick()
        start.assert_awaited_once_with(self.conn,'start')
        queued=[self.conn.tts.tts_text_queue.get_nowait() for _ in range(3)]
        self.assertEqual([item.sentence_type for item in queued],[SentenceType.FIRST,SentenceType.MIDDLE,SentenceType.LAST])
        self.assertEqual(queued[1].content_detail,'现在方便聊两句吗？')
        self.assertFalse(any('[后台主动消息任务' in (item.content or '') for item in self.dialogue.dialogue))
        with self.runtime.store._connect() as db:
            self.assertEqual(db.execute('SELECT status FROM proactive_attempts').fetchone()[0],'queued')
        self.runtime.record_sent('actual-transport-send',self.conn.sentence_id)
        with self.runtime.store._connect() as db:
            self.assertEqual(db.execute('SELECT status FROM proactive_attempts').fetchone()[0],'sent')

    async def test_incoming_voice_cancels_proactive_before_transcription_finishes(self):
        self.enable('proactive-messaging')
        self.runtime.begin_turn('before-idle')
        self.now+=timedelta(hours=3)
        def responding(*_):
            self.conn.client_have_voice=True
            return iter(['现在方便聊两句吗？'])
        self.conn.llm.response=responding
        await self.runtime.tick()
        self.assertEqual(self.sent,[])

    async def test_bot_greeting_alone_does_not_count_as_first_user_interaction(self):
        self.enable('proactive-messaging')
        self.runtime.record_sent('automatic-greeting')
        self.now+=timedelta(hours=3)
        await self.runtime.tick()
        self.assertEqual(self.sent,[])

    async def test_control_updates_continue_while_proactive_model_is_busy(self):
        self.enable('proactive-messaging')
        self.runtime.begin_turn('before-idle')
        self.now+=timedelta(hours=3)
        self.conn.config['read_config_from_api']=True
        release=threading.Event()
        started=threading.Event()
        def slow_response(*_):
            started.set()
            release.wait(2)
            return iter(['[SKIP]'])
        self.conn.llm.response=slow_response
        api=SimpleNamespace(get_agent_plugins=AsyncMock(return_value={
            'revision':1,'scope':self.runtime.scope,'plugins':states('proactive-messaging')}),
            report_agent_plugins=AsyncMock())
        original_sleep=asyncio.sleep
        async def quick_poll(_): await original_sleep(0.01)
        with patch.dict(sys.modules,{'config.manage_api_client':api}), patch('core.plugins.runtime.asyncio.sleep',new=quick_poll):
            try:
                await self.runtime.start()
                for _ in range(100):
                    if started.is_set() and api.report_agent_plugins.await_count>=2: break
                    await original_sleep(0.01)
                self.assertTrue(started.is_set())
                self.assertGreaterEqual(api.report_agent_plugins.await_count,2)
                self.assertTrue(self.runtime.generating_proactive)
            finally:
                release.set()
                await self.runtime.close()

    async def test_image_endpoint_blocks_private_networks_and_preserves_operator_exception(self):
        for url in ['https://127.0.0.1/images', 'https://169.254.169.254/images', 'http://93.184.216.34/images', 'https://[::1]/images']:
            with self.subTest(url=url), self.assertRaises(ValueError): await resolve_endpoint(url)
        mixed=[(socket.AF_INET,socket.SOCK_STREAM,0,'',(address,443)) for address in ['93.184.216.34','10.0.0.1']]
        with patch('socket.getaddrinfo',return_value=mixed):
            with self.assertRaises(ValueError): await resolve_endpoint('https://images.example.test/v1/images/generations')
        target,host,server_name=await resolve_endpoint('http://127.0.0.1:8188/images', ['http://127.0.0.1:8188'])
        self.assertEqual(str(target),'http://127.0.0.1:8188/images')
        self.assertEqual(host,'127.0.0.1:8188')
        self.assertEqual(server_name,'127.0.0.1')
        with self.assertRaises(ValueError): await resolve_endpoint('http://127.0.0.1:8189/images', ['http://127.0.0.1:8188'])


if __name__ == '__main__': unittest.main()
