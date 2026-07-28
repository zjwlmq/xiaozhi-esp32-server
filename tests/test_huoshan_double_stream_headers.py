import ast
import unittest
import uuid
from pathlib import Path


SOURCE_FILE = (
    Path(__file__).resolve().parents[1]
    / "main"
    / "xiaozhi-server"
    / "core"
    / "providers"
    / "tts"
    / "huoshan_double_stream.py"
)


def load_header_builder():
    """只编译待测方法，避免测试依赖完整服务端运行环境。"""
    tree = ast.parse(SOURCE_FILE.read_text(encoding="utf-8"))
    provider = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TTSProvider"
    )
    method = next(
        node
        for node in provider.body
        if isinstance(node, ast.FunctionDef) and node.name == "_build_ws_headers"
    )
    test_class = ast.ClassDef(
        name="HeaderBuilder",
        bases=[],
        keywords=[],
        body=[method],
        decorator_list=[],
    )
    isolated_module = ast.fix_missing_locations(
        ast.Module(body=[test_class], type_ignores=[])
    )
    namespace = {"uuid": uuid}
    exec(compile(isolated_module, str(SOURCE_FILE), "exec"), namespace)
    return namespace["HeaderBuilder"]


class HuoshanDoubleStreamHeaderTest(unittest.TestCase):
    def make_provider(self, api_key=""):
        provider = load_header_builder()()
        provider.api_key = api_key
        provider.appId = "test-app-id"
        provider.access_token = "test-access-token"
        provider.resource_id = "seed-tts-1.0"
        return provider

    def test_api_key_takes_precedence(self):
        headers = self.make_provider("test-api-key")._build_ws_headers()

        self.assertEqual(headers["X-Api-Key"], "test-api-key")
        self.assertNotIn("X-Api-App-Key", headers)
        self.assertNotIn("X-Api-Access-Key", headers)

    def test_legacy_headers_are_kept_as_fallback(self):
        headers = self.make_provider()._build_ws_headers()

        self.assertEqual(headers["X-Api-App-Key"], "test-app-id")
        self.assertEqual(headers["X-Api-Access-Key"], "test-access-token")
        self.assertNotIn("X-Api-Key", headers)

    def test_resource_and_connect_id_are_always_present(self):
        provider = self.make_provider("test-api-key")
        first = provider._build_ws_headers()
        second = provider._build_ws_headers()

        self.assertEqual(first["X-Api-Resource-Id"], "seed-tts-1.0")
        self.assertNotEqual(first["X-Api-Connect-Id"], second["X-Api-Connect-Id"])
        uuid.UUID(first["X-Api-Connect-Id"])

    def test_all_websocket_connections_use_the_shared_builder(self):
        tree = ast.parse(SOURCE_FILE.read_text(encoding="utf-8"))
        connect_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "connect"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "websockets"
        ]
        builder_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_build_ws_headers"
        ]

        self.assertEqual(len(connect_calls), 2)
        self.assertEqual(len(builder_calls), 2)
        for call in connect_calls:
            header_keyword = next(
                keyword
                for keyword in call.keywords
                if keyword.arg == "additional_headers"
            )
            self.assertIsInstance(header_keyword.value, ast.Name)
            self.assertEqual(header_keyword.value.id, "ws_header")


if __name__ == "__main__":
    unittest.main()
