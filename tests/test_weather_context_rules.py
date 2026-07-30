import ast
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "main" / "xiaozhi-server"
WEATHER_SOURCE = SERVER_ROOT / "plugins_func" / "functions" / "get_weather.py"
PROMPT_MANAGER_SOURCE = SERVER_ROOT / "core" / "utils" / "prompt_manager.py"
BASE_PROMPT = SERVER_ROOT / "agent-base-prompt.txt"
sys.path.insert(0, str(SERVER_ROOT))


class _DummyLogger:
    def bind(self, **kwargs):
        return self

    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


logger_module = types.ModuleType("config.logger")
logger_module.setup_logging = lambda *args, **kwargs: _DummyLogger()
sys.modules.setdefault("config.logger", logger_module)

from core.utils.prompt_manager import PromptManager  # noqa: E402


def load_weather_descriptor():
    tree = ast.parse(WEATHER_SOURCE.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "GET_WEATHER_FUNCTION_DESC"
            for target in node.targets
        )
    )
    return ast.literal_eval(assignment.value)


def load_weather_normalizer():
    tree = ast.parse(PROMPT_MANAGER_SOURCE.read_text(encoding="utf-8"))
    marker_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "WEATHER_FAILURE_MARKERS"
            for target in node.targets
        )
    )
    normalizer = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_normalize_weather_info"
    )
    isolated_module = ast.fix_missing_locations(
        ast.Module(body=[marker_assignment, normalizer], type_ignores=[])
    )
    namespace = {"Any": object}
    exec(compile(isolated_module, str(PROMPT_MANAGER_SOURCE), "exec"), namespace)
    return namespace["_normalize_weather_info"]


class WeatherToolDescriptionTests(unittest.TestCase):
    def test_description_uses_conditional_weather_context(self):
        descriptor = load_weather_descriptor()["function"]
        description = descriptor["description"]

        self.assertNotIn("绝对不要调用", description)
        self.assertIn("用户明确指定地点时", description)
        self.assertIn("上下文天气缺失、获取失败、已过期", description)
        self.assertIn("可省略location", description)

    def test_lang_is_optional_because_runtime_has_a_default(self):
        parameters = load_weather_descriptor()["function"]["parameters"]

        self.assertEqual(parameters["required"], [])
        self.assertIn("默认zh_CN", parameters["properties"]["lang"]["description"])


class WeatherContextTests(unittest.TestCase):
    def test_empty_and_failure_values_are_not_valid_context(self):
        normalize = load_weather_normalizer()

        for value in (
            None,
            "",
            "   ",
            "天气信息获取失败",
            "请求失败",
            "未找到相关的城市: 广州，请确认地点是否正确",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize(value), "")

    def test_valid_weather_text_is_preserved(self):
        normalize = load_weather_normalizer()
        report = "您查询的位置是：广州\n未来7天预报：\n明天：晴，20~28℃"

        self.assertEqual(normalize(f"  {report}\n"), report)

    def test_failed_cached_weather_is_not_rendered_as_context(self):
        class CacheType:
            LOCATION = "location"
            WEATHER = "weather"
            DEVICE_PROMPT = "device_prompt"

        class Cache:
            def __init__(self):
                self.values = {
                    (CacheType.LOCATION, "127.0.0.1"): "广州",
                    (CacheType.WEATHER, "广州"): "天气信息获取失败",
                }
                self.deleted = []

            def get(self, cache_type, key):
                return self.values.get((cache_type, key))

            def set(self, cache_type, key, value):
                self.values[(cache_type, key)] = value

            def delete(self, cache_type, key):
                self.deleted.append((cache_type, key))
                self.values.pop((cache_type, key), None)

        manager = PromptManager.__new__(PromptManager)
        manager.base_prompt_template = (
            "{% if weather_info %}weather={{ weather_info }}"
            "{% else %}weather=unavailable{% endif %}"
        )
        manager.cache_manager = Cache()
        manager.CacheType = CacheType
        manager.config = {}
        manager.context_data = {}
        manager.logger = _DummyLogger()
        manager._get_current_time_info = lambda: ("2026-07-31", "星期五", "")

        prompt = manager.build_enhanced_prompt(
            "test prompt", "device-1", client_ip="127.0.0.1"
        )

        self.assertEqual(prompt, "weather=unavailable")
        self.assertEqual(manager.cache_manager.deleted, [(CacheType.WEATHER, "广州")])

    def test_base_prompt_requires_tool_when_weather_context_is_unavailable(self):
        prompt = BASE_PROMPT.read_text(encoding="utf-8")

        self.assertNotIn(
            "The context already provides the local 7-day forecast", prompt
        )
        self.assertNotIn(
            "User asks ”明天天气” → you call get_weather (WRONG!", prompt
        )
        self.assertIn(
            "when `weather_info` is missing, unavailable, failed, or stale", prompt
        )
        self.assertIn(
            "Local upcoming weather: unavailable. For weather requests, call get_weather",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
