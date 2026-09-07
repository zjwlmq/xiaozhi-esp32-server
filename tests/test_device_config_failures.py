"""Exercise configuration decisions without loading audio models or real APIs."""
import ast
import asyncio
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock


SERVER = Path(__file__).resolve().parents[1] / "main" / "xiaozhi-server"


class DeviceNotFoundException(Exception):
    pass


class DeviceBindException(Exception):
    def __init__(self, bind_code):
        self.bind_code = bind_code


def load_subjects(namespace):
    loader_path = SERVER / "config/config_loader.py"
    loader = ast.parse(loader_path.read_text(encoding="utf-8"))
    fetch = next(node for node in loader.body
                 if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_private_config_from_api")
    # Match the existing lightweight provider tests: execute the real methods,
    # substitute only infrastructure that would otherwise start models/services.
    exec(compile(ast.Module(body=[fetch], type_ignores=[]), str(loader_path), "exec"), namespace)
    connection_path = SERVER / "core/connection.py"
    tree = ast.parse(connection_path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "ConnectionHandler")
    for name in ("_initialize_private_config_async", "_background_initialize"):
        method = next(node for node in cls.body
                      if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(connection_path), "exec"), namespace)


class DeviceConfigFailureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = AsyncMock(return_value={"selected_module": {}})
        self.words = AsyncMock(return_value=None)
        self.namespace = {
            "asyncio": asyncio, "json": json, "time": time, "TAG": "test",
            "get_agent_models": self.api, "get_correct_words": self.words,
            "DeviceNotFoundException": DeviceNotFoundException,
            "DeviceBindException": DeviceBindException,
            "check_vad_update": lambda *_: False,
            "check_asr_update": lambda *_: False,
            "filter_sensitive_info": lambda value: value,
            "initialize_modules": lambda *_: {},
        }
        load_subjects(self.namespace)

    async def fetch(self):
        return await self.namespace["get_private_config_from_api"](
            {"selected_module": {}}, "test-device", "test-client")

    def connection(self):
        logger = Mock()
        logger.bind.return_value = logger
        conn = SimpleNamespace(
            read_config_from_api=True, need_bind=False,
            bind_completed_event=asyncio.Event(), bind_code=None,
            config={"selected_module": {}}, common_config={},
            headers={"device-id": "test-device", "client-id": "test-client"},
            logger=logger, websocket=SimpleNamespace(close=AsyncMock()),
            loop=asyncio.get_running_loop(), executor=Mock(), _initialize_components=Mock(),
        )
        conn._initialize_private_config_async = lambda: self.namespace["_initialize_private_config_async"](conn)
        return conn

    async def test_required_api_errors_are_propagated(self):
        for error in (TimeoutError("offline"), RuntimeError("API rejected"),
                      DeviceNotFoundException(), DeviceBindException("123456")):
            with self.subTest(error=type(error).__name__):
                self.api.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    await self.fetch()
                self.assertIs(caught.exception, error)

    async def test_cancelled_device_lookup_is_not_a_success(self):
        self.api.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.fetch()

    async def test_invalid_success_payload_is_rejected(self):
        for value in (None, {}, [], "invalid", False):
            with self.subTest(value=value):
                self.api.return_value = value
                with self.assertRaises(ValueError):
                    await self.fetch()

    async def test_optional_replacement_words_failure_keeps_valid_device_config(self):
        self.words.side_effect = TimeoutError("optional service unavailable")
        self.assertEqual(await self.fetch(), {"selected_module": {}})

    async def test_replacement_words_do_not_modify_the_api_response(self):
        config = {"selected_module": {}}
        self.api.return_value = config
        self.words.return_value = {"old": "new"}
        self.assertEqual((await self.fetch())["correct_words"], {"old": "new"})
        self.assertNotIn("correct_words", config)

    async def test_configuration_failure_closes_connection_without_initializing_public_models(self):
        for error in (TimeoutError("offline"), RuntimeError("API rejected")):
            with self.subTest(error=type(error).__name__):
                self.api.side_effect = error
                conn = self.connection()
                await self.namespace["_background_initialize"](conn)
                self.assertTrue(conn.need_bind)
                self.assertFalse(conn.bind_completed_event.is_set())
                conn.websocket.close.assert_awaited_once_with(
                    code=1011, reason="Device configuration unavailable")
                conn.executor.submit.assert_not_called()

    async def test_binding_responses_still_use_the_binding_prompt_path(self):
        for error in (DeviceNotFoundException(), DeviceBindException("123456")):
            with self.subTest(error=type(error).__name__):
                self.api.side_effect = error
                conn = self.connection()
                await self.namespace["_background_initialize"](conn)
                self.assertTrue(conn.need_bind)
                conn.websocket.close.assert_not_awaited()
                conn.executor.submit.assert_called_once_with(conn._initialize_components)
                if isinstance(error, DeviceBindException):
                    self.assertEqual(conn.bind_code, "123456")

    async def test_success_and_local_mode_still_initialize(self):
        for from_api in (True, False):
            with self.subTest(from_api=from_api):
                conn = self.connection()
                conn.read_config_from_api = from_api
                await self.namespace["_background_initialize"](conn)
                self.assertFalse(conn.need_bind)
                self.assertTrue(conn.bind_completed_event.is_set())
                conn.websocket.close.assert_not_awaited()
                conn.executor.submit.assert_called_once_with(conn._initialize_components)


if __name__ == "__main__":
    unittest.main()
