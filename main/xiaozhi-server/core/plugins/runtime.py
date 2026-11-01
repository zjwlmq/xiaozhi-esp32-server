"""Connection-scoped plugin lifecycle, persistent time, and optional background work."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
import uuid

from .context_plugins import holiday_context, in_quiet_hours, optimize_memory
from .image_generation import generate_image
from .settings import MANIFESTS, defaults, missing_fields, normalize
from .time_context import TimeContextStore, get_timezone

LOG = logging.getLogger(__name__)


class PluginRuntime:
    def __init__(self, conn, state_path=None, clock=None):
        self.conn = conn
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = TimeContextStore(state_path or Path('data/plugin-center/live.sqlite3'), clock=self.clock)
        self.states, self.errors, self.revision = {}, {}, 0
        self.scope = 'local:' + str(getattr(conn, 'device_id', 'unknown'))
        self.user_event_id = None
        self.task = None
        self.proactive_task = None
        self.closed = False
        self.control_unavailable = False
        self.generating_proactive = False
        self.pending_proactive = {}
        self._refresh_lock = asyncio.Lock()
        self._last_refresh = 0
        with self.store._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS proactive_attempts (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, attempted_at REAL NOT NULL,
                local_day TEXT NOT NULL, status TEXT NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS proactive_by_scope ON proactive_attempts(scope,attempted_at)')
        self.apply_config(conn.config.get('plugin_center', {}))

    def apply_config(self, packet):
        states = normalize(packet.get('plugins', {}))
        changed = states != self.states
        self.states = states
        self.revision = packet.get('revision', 0)
        new_scope = packet.get('scope')
        if new_scope and new_scope != self.scope:
            self.scope = new_scope
            self.user_event_id = None
        zone = self.settings('time-awareness')['timezone']
        self.store.timezone_name, self.store.tz = zone, get_timezone(zone)
        if changed:
            self.errors.clear()
            handler = getattr(self.conn, 'func_handler', None)
            if handler is not None:
                handler.tool_manager._invalidate_cache()

    def settings(self, plugin_id):
        return self.states.get(plugin_id, {}).get('settings', defaults(plugin_id))

    def enabled(self, plugin_id):
        if self.control_unavailable and plugin_id in ('proactive-messaging', 'image-generation'):
            return False
        return bool(self.states.get(plugin_id, {}).get('enabled'))

    def _error(self, plugin_id, exc):
        # Provider errors can contain URLs or secrets. Export only a bounded error category.
        self.errors[plugin_id] = '运行失败：' + type(exc).__name__
        LOG.warning('Plugin %s failed (%s)', plugin_id, type(exc).__name__)

    async def refresh(self, force=False):
        if not self.conn.config.get('read_config_from_api'):
            return
        async with self._refresh_lock:
            if not force and time.monotonic() - self._last_refresh < 2:
                return
            from config.manage_api_client import get_agent_plugins
            try:
                packet = await asyncio.wait_for(get_agent_plugins(self.conn.device_id), timeout=3)
                self.apply_config(packet)
                self.control_unavailable = False
                self._last_refresh = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.control_unavailable = True
                LOG.warning('Plugin configuration unavailable (%s)', type(exc).__name__)

    async def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._watch())

    async def close(self):
        self.closed = True
        tasks = [task for task in (self.task, self.proactive_task) if task and task is not asyncio.current_task()]
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
        self.task = None
        self.proactive_task = None

    async def _watch(self):
        while not self.closed:
            try:
                await self.refresh(force=True)
                if self.conn.config.get('read_config_from_api') and not self.control_unavailable:
                    from config.manage_api_client import report_agent_plugins
                    await asyncio.wait_for(report_agent_plugins(self.conn.device_id, self.snapshot()), timeout=3)
                if self.enabled('proactive-messaging') and (self.proactive_task is None or self.proactive_task.done()):
                    self.proactive_task = asyncio.create_task(self._tick_guarded())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning('Plugin monitor failed (%s)', type(exc).__name__)
            await asyncio.sleep(15)

    async def _tick_guarded(self):
        try: await self.tick()
        except asyncio.CancelledError: raise
        except Exception as exc: self._error('proactive-messaging', exc)

    def begin_turn(self, event_id=None, event_at=None):
        self.user_event_id = event_id or str(uuid.uuid4())
        self.store.observe_user_message(self.scope, self.user_event_id, event_at)

    def record_sent(self, event_id, sentence_id=None):
        self.store.record_reply_sent(self.scope, event_id)
        if sentence_id in self.pending_proactive:
            self._finish_attempt(self.pending_proactive.pop(sentence_id), 'sent')

    def now(self):
        return self.clock().astimezone(get_timezone(self.settings('time-awareness')['timezone']))

    def prepare_memory(self, memory, query):
        if self.enabled('memory-optimizer'):
            try:
                result = optimize_memory(memory, query, self.settings('memory-optimizer'))
                self.errors.pop('memory-optimizer', None)
                return result
            except Exception as exc: self._error('memory-optimizer', exc)
        return memory

    def augment_prompt(self, prompt):
        if self.enabled('time-awareness') and self.user_event_id:
            try: prompt = self.store.build_system_prompt(prompt, self.scope, self.user_event_id)
            except Exception as exc: self._error('time-awareness', exc)
        if self.enabled('holiday-awareness'):
            try:
                data = holiday_context(self.now(), self.settings('holiday-awareness'))
                prompt += '\n<holiday_context>\n' + json.dumps(data, ensure_ascii=False) + '\n</holiday_context>'
            except Exception as exc: self._error('holiday-awareness', exc)
        return prompt

    def status(self, plugin_id):
        if not self.states.get(plugin_id, {}).get('enabled'): return ('disabled', '未启用')
        if self.control_unavailable: return ('waiting', '配置服务暂不可用')
        if plugin_id in self.errors: return ('error', self.errors[plugin_id])
        missing = missing_fields(plugin_id, self.settings(plugin_id))
        if missing: return ('needs_config', '请设置' + '、'.join(missing))
        if plugin_id == 'image-generation':
            if not (getattr(self.conn, 'features', None) or {}).get('plugin_images'):
                return ('waiting', '当前客户端尚未声明支持图片消息')
            if getattr(self.conn, 'intent_type', None) != 'function_call':
                return ('needs_config', '请为智能体选择函数调用模式')
        if plugin_id == 'memory-optimizer' and getattr(self.conn, 'memory', None) is None:
            return ('waiting', '等待记忆模块提供内容')
        if plugin_id == 'proactive-messaging': return ('ready', '仅在当前设备在线且允许的时段发送')
        return ('ready', '已加载')

    def snapshot(self):
        return {'revision': self.revision, 'observed_at': self.clock().timestamp(),
                'plugins': {pid: {'state': self.status(pid)[0], 'detail': self.status(pid)[1]} for pid in MANIFESTS}}

    def image_tool_ready(self):
        return (self.enabled('image-generation') and not self.closed
                and not missing_fields('image-generation', self.settings('image-generation'))
                and (getattr(self.conn, 'features', None) or {}).get('plugin_images')
                and getattr(self.conn, 'intent_type', None) == 'function_call')

    async def execute_image(self, prompt):
        await self.refresh(force=True)
        if not self.image_tool_ready(): raise ValueError('生图插件未就绪')
        try:
            media = await generate_image(self.settings('image-generation'), prompt,
                allowed_origins=self.conn.config.get('plugin_center_image_allowed_origins', []))
            await self.refresh(force=True)
            if not self.image_tool_ready() or self.closed: raise ValueError('生图插件已关闭，结果未发送')
            event_id = str(uuid.uuid4())
            await self.conn.websocket.send(json.dumps({'type': 'plugin_image', 'id': event_id,
                'session_id': self.conn.session_id, 'origin': 'generated', 'created_at': self.now().isoformat(),
                'alt': '生成的图片', **media}, ensure_ascii=False))
            self.record_sent(event_id)
            self.errors.pop('image-generation', None)
            return {'status': 'sent', 'media_id': event_id, 'origin': 'generated'}
        except Exception as exc:
            self._error('image-generation', exc)
            raise

    def _reserve_attempt(self, now, settings):
        interval = settings['interval_minutes'] * 60
        with self.store._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM interactions WHERE conversation_key=? AND role='user' LIMIT 1", (self.scope,)).fetchone():
                return None
            latest = db.execute('SELECT MAX(event_at) FROM interactions WHERE conversation_key=?', (self.scope,)).fetchone()[0]
            if latest is None or now.timestamp() - latest < interval: return None
            last_attempt = db.execute('SELECT MAX(attempted_at) FROM proactive_attempts WHERE scope=?', (self.scope,)).fetchone()[0]
            if last_attempt is not None and now.timestamp() - last_attempt < interval: return None
            count = db.execute("SELECT COUNT(*) FROM proactive_attempts WHERE scope=? AND local_day=? AND status IN ('reserved','queued','sent')", (self.scope, now.date().isoformat())).fetchone()[0]
            if count >= settings['daily_limit']: return None
            attempt_id = str(uuid.uuid4())
            db.execute('INSERT INTO proactive_attempts VALUES (?,?,?,?,?)', (attempt_id, self.scope, now.timestamp(), now.date().isoformat(), 'reserved'))
            return attempt_id

    def _finish_attempt(self, attempt_id, state):
        with self.store._connect() as db:
            db.execute('UPDATE proactive_attempts SET status=? WHERE id=? AND scope=?', (state, attempt_id, self.scope))

    async def tick(self):
        if not self.enabled('proactive-messaging') or self.closed or self.generating_proactive:
            return
        if getattr(self.conn, 'client_is_speaking', False) or getattr(self.conn, 'client_have_voice', False):
            return
        settings = self.settings('proactive-messaging')
        now = self.now()
        if in_quiet_hours(now, settings['quiet_start'], settings['quiet_end']): return
        attempt_id = self._reserve_attempt(now, settings)
        if not attempt_id: return
        self.generating_proactive = True
        original_user_event = self.user_event_id
        try:
            messages = deepcopy(self.conn.dialogue.get_llm_dialogue_with_memory())
            messages.append({'role': 'user', 'content': '[后台主动消息任务，非用户发言] 当前时间：' + now.isoformat()
                + '。' + settings['instruction'] + '只输出一两句自然聊天；不适合打扰时只输出[SKIP]。不要声称刚收到用户消息。'})
            def collect():
                result = ''
                stream = self.conn.llm.response(self.conn.session_id, messages)
                try:
                    for chunk in stream:
                        if isinstance(chunk, str): result += chunk
                        if len(result) > 1200: break
                finally:
                    if hasattr(stream, 'close'): stream.close()
                return result.strip()
            text = await asyncio.wait_for(asyncio.to_thread(collect), timeout=45)
            await self.refresh(force=True)
            latest = self.settings('proactive-messaging')
            if (not self.enabled('proactive-messaging') or self.closed or original_user_event != self.user_event_id
                    or getattr(self.conn, 'client_is_speaking', False)
                    or getattr(self.conn, 'client_have_voice', False)
                    or in_quiet_hours(self.now(), latest['quiet_start'], latest['quiet_end'])):
                self._finish_attempt(attempt_id, 'cancelled')
                return
            if not text or text in ('[SKIP]', 'SKIP') or len(text) > 1200:
                self._finish_attempt(attempt_id, 'skipped')
                self.errors.pop('proactive-messaging', None)
                return
            sender = getattr(self.conn, 'plugin_send_text', None)
            if sender:
                await sender(text)
                self.record_sent(attempt_id)
                self._finish_attempt(attempt_id, 'sent')
            else:
                from core.handle.sendAudioHandle import send_tts_message
                from core.providers.tts.dto.dto import TTSMessageDTO, SentenceType, ContentType
                from core.utils.dialogue import Message
                sentence_id = str(uuid.uuid4())
                self.conn.sentence_id = sentence_id
                self.conn.client_abort = False
                self.conn.client_is_speaking = True
                self.pending_proactive[sentence_id] = attempt_id
                await send_tts_message(self.conn, 'start')
                for kind, content, value in [(SentenceType.FIRST, ContentType.ACTION, None),
                                             (SentenceType.MIDDLE, ContentType.TEXT, text),
                                             (SentenceType.LAST, ContentType.ACTION, None)]:
                    self.conn.tts.tts_text_queue.put(TTSMessageDTO(sentence_id=sentence_id, sentence_type=kind,
                                                                content_type=content, content_detail=value))
                self.conn.dialogue.put(Message(role='assistant', content=text))
                self._finish_attempt(attempt_id, 'queued')
            self.errors.pop('proactive-messaging', None)
        except asyncio.CancelledError:
            self._finish_attempt(attempt_id, 'cancelled')
            raise
        except Exception as exc:
            self._finish_attempt(attempt_id, 'failed')
            self._error('proactive-messaging', exc)
        finally:
            self.generating_proactive = False
