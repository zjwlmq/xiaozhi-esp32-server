"""Protocol stop must follow all previously queued audio, including slow frames."""
import ast
import asyncio
import queue
import threading
import traceback
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


SERVER = Path(__file__).resolve().parents[1] / "main/xiaozhi-server"


def load_methods(path, class_name, names, namespace):
    tree = ast.parse((SERVER / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    methods = [node for node in cls.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    subject = ast.ClassDef(name="Subject", bases=[], keywords=[], body=methods, decorator_list=[])
    annotations = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[annotations, subject], type_ignores=[]))
    exec(compile(module, str(SERVER / path), "exec"), namespace)
    return namespace["Subject"]


class ASRStopOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_waits_for_final_frames_for_batch_and_streaming_asr(self):
        for interface in ("batch", "stream"):
            with self.subTest(interface=interface):
                entered = asyncio.Event()
                release = asyncio.Event()
                processed = []

                async def process_audio(conn, frame):
                    entered.set()
                    await release.wait()
                    processed.append(frame)
                    conn.asr_audio.append(frame)

                logger = Mock()
                logger.bind.return_value = logger
                namespace = dict(asyncio=asyncio, queue=queue, Future=Future,
                                 traceback=traceback, logger=logger, TAG="test",
                                 handleAudioMessage=process_audio,
                                 InterfaceType=SimpleNamespace(STREAM="stream"))
                provider_class = load_methods(
                    "core/providers/asr/base.py", "ASRProviderBase",
                    {"asr_text_priority_thread", "wait_for_audio_processed"}, namespace)
                handler_class = load_methods(
                    "core/handle/textHandler/listenMessageHandler.py", "ListenTextMessageHandler",
                    {"handle"}, namespace)
                provider = provider_class()
                provider.interface_type = interface
                provider.handle_voice_stop = AsyncMock()
                provider._send_stop_request = AsyncMock()
                conn = SimpleNamespace(asr=provider, asr_audio=[], asr_audio_queue=queue.Queue(),
                                       stop_event=threading.Event(), client_voice_stop=False,
                                       loop=asyncio.get_running_loop())
                conn.reset_audio_states = lambda: conn.asr_audio.clear()
                conn.asr_audio_queue.put(b"first")
                conn.asr_audio_queue.put(b"last")
                worker = threading.Thread(target=provider.asr_text_priority_thread, args=(conn,), daemon=True)
                worker.start()
                stop = asyncio.create_task(handler_class().handle(conn, {"state": "stop"}))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=2)
                    self.assertFalse(stop.done())
                    provider.handle_voice_stop.assert_not_awaited()
                    provider._send_stop_request.assert_not_awaited()
                    release.set()
                    await asyncio.wait_for(stop, timeout=2)
                    await asyncio.sleep(0)
                    self.assertEqual(processed, [b"first", b"last"])
                    if interface == "batch":
                        provider.handle_voice_stop.assert_awaited_once_with(conn, [b"first", b"last"])
                    else:
                        provider._send_stop_request.assert_awaited_once()
                    logger.error.assert_not_called()
                finally:
                    release.set()
                    conn.stop_event.set()
                    await asyncio.to_thread(worker.join, 2)
                    if not stop.done():
                        stop.cancel()


if __name__ == "__main__":
    unittest.main()
