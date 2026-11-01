"""Consume the normal chat/TTS queue without invoking a speech provider."""
import asyncio
import json
import queue
import threading
import uuid

from core.providers.tts.dto.dto import ContentType, SentenceType, TTSMessageDTO


class TextTTS:
    def __init__(self):
        self.tts_text_queue = queue.Queue()
        self.tts_audio_queue = queue.Queue()
        self._texts = {}
        self._closed = threading.Event()
        self._pending = None
        self._thread = None
        self._audio_thread = None
        self.tts_audio_first_sentence = True

    async def open_audio_channels(self, conn):
        self.conn = conn
        self._thread = threading.Thread(target=self._consume, daemon=True, name="qq-text-output")
        self._thread.start()
        # Quota/binding/legacy tool notices can use the audio queue directly.
        self._audio_thread = threading.Thread(target=self._consume_audio_notices, daemon=True, name="qq-text-notices")
        self._audio_thread.start()

    def _consume_audio_notices(self):
        while not self._closed.is_set() and not self.conn.stop_event.is_set():
            try:
                item = self.tts_audio_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            kind, _, text = item[:3]
            sentence = item[3] if len(item) > 3 else self.conn.sentence_id
            if sentence is None:
                sentence = self.conn.sentence_id = uuid.uuid4().hex
            self.tts_text_queue.put(TTSMessageDTO(sentence, kind,
                ContentType.TEXT if text else ContentType.ACTION, text))

    def store_tts_text(self, sentence_id, text):
        self._texts[sentence_id] = text
        if len(self._texts) > 5:
            self._texts.pop(next(iter(self._texts)))

    def get_tts_text(self, sentence_id):
        return self._texts.get(sentence_id)

    def clear_tts_text(self, sentence_id):
        self._texts.pop(sentence_id, None)

    def tts_one_sentence(self, conn, content_type, content_detail=None, content_file=None, sentence_id=None):
        self.tts_text_queue.put(TTSMessageDTO(sentence_id or conn.sentence_id, SentenceType.MIDDLE,
                                             content_type, content_detail, content_file))

    def _consume(self):
        parts, sentence = [], None
        while not self._closed.is_set() and not self.conn.stop_event.is_set():
            try:
                item = self.tts_text_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if self.conn.client_abort or item.sentence_id != self.conn.sentence_id:
                continue
            if item.sentence_id != sentence or item.sentence_type == SentenceType.FIRST:
                parts, sentence = [], item.sentence_id
            if item.content_type == ContentType.TEXT and item.content_detail:
                parts.append(item.content_detail)
            if item.sentence_type == SentenceType.LAST:
                self._pending = asyncio.run_coroutine_threadsafe(self._deliver("".join(parts), sentence), self.conn.loop)
                try:
                    self._pending.result(timeout=180)
                except Exception:
                    self._pending.cancel()
                    asyncio.run_coroutine_threadsafe(self.conn.websocket.close(code=1011, reason="QQ delivery failed"), self.conn.loop)
                    return
                finally:
                    self._pending = None
                parts = []

    async def _deliver(self, text, sentence):
        if text.strip():
            await self.conn.websocket.send(json.dumps({"type": "qq_text", "text": text, "sentence_id": sentence}))
        self.conn.clearSpeakStatus()
        await self.conn.websocket.send(json.dumps({"type": "tts", "state": "stop"}))

    async def close(self):
        self._closed.set()
        if self._pending:
            self._pending.cancel()
        if self._thread:
            await asyncio.to_thread(self._thread.join, 1)
        if self._audio_thread:
            await asyncio.to_thread(self._audio_thread.join, 1)
