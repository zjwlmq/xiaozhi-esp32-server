import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "main" / "xiaozhi-server"
sys.path.insert(0, str(SERVER_ROOT))


class _Logger:
    def bind(self, **kwargs):
        return self

    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


logger_module = types.ModuleType("config.logger")
logger_module.setup_logging = lambda *args, **kwargs: _Logger()
sys.modules.setdefault("config.logger", logger_module)

import core.providers.memory.nixi_life.nixi_life as nixi_memory_module  # noqa: E402
from core.providers.memory.nixi_life.nixi_life import (  # noqa: E402
    MemoryProvider,
    NixiLifeMemoryStore,
)
from core.utils.dialogue import Message  # noqa: E402


class _FakeLLM:
    def __init__(self, response):
        self.response = response

    def response_no_stream(self, *args, **kwargs):
        return json.dumps(self.response, ensure_ascii=False)


def action(**overrides):
    value = {
        "operation": "add",
        "target_id": None,
        "kind": "event",
        "visibility": "shared",
        "status": "completed",
        "content": "女儿和两位父亲一起吃了晚饭",
        "event_at": "2026-09-03T19:00:00+08:00",
        "importance": 3,
        "evidence_role": "user",
        "evidence_quote": "今晚我们一起吃了晚饭",
    }
    value.update(overrides)
    return value


class NixiLifeMemoryStoreTests(unittest.TestCase):
    def test_user_fact_persists_but_assistant_invention_cannot_be_history(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NixiLifeMemoryStore(Path(temp), "7", "nixi-family")
            messages = [
                ("user", "今晚我们一起吃了晚饭"),
                ("assistant", "上个月我们还去了三亚"),
            ]
            applied = store.apply_actions(
                [
                    action(),
                    action(
                        content="三人上个月去了三亚",
                        evidence_role="assistant",
                        evidence_quote="上个月我们还去了三亚",
                    ),
                ],
                messages,
                "s1",
            )
            self.assertEqual(applied, 1)
            records = store.load()["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "completed")

    def test_assistant_plan_is_pending_and_passing_date_does_not_complete_it(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NixiLifeMemoryStore(Path(temp), "7", "nixi-family")
            proposed = action(
                kind="plan",
                status="pending",
                content="池骋提议周末带女儿去海边",
                event_at="2020-01-01T09:00:00+08:00",
                evidence_role="assistant",
                evidence_quote="周末带你去海边",
            )
            self.assertEqual(
                store.apply_actions(
                    [proposed], [("assistant", "周末带你去海边")], "s2"
                ),
                1,
            )
            record = store.load()["records"][0]
            self.assertEqual(record["status"], "pending")

    def test_exact_user_evidence_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NixiLifeMemoryStore(Path(temp), "7", "nixi-family")
            self.assertEqual(
                store.apply_actions(
                    [action(evidence_quote="一句并不存在的话")],
                    [("user", "今晚我们一起吃了晚饭")],
                    "s3",
                ),
                0,
            )
            self.assertEqual(store.load()["records"], [])

    def test_completion_requires_user_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NixiLifeMemoryStore(Path(temp), "7", "nixi-family")
            planned = action(
                kind="plan",
                status="planned",
                content="三人九月五日去三亚",
                event_at="2026-09-05T08:00:00+08:00",
                evidence_quote="我们九月五日去三亚",
            )
            store.apply_actions(
                [planned], [("user", "我们九月五日去三亚")], "s4"
            )
            target = store.load()["records"][0]["id"]
            completed = action(
                operation="complete",
                target_id=target,
                kind="plan",
                status="completed",
                content="三人已经去了三亚",
                evidence_quote="我们已经到三亚了",
                event_at="2026-09-05T11:00:00+08:00",
            )
            self.assertEqual(
                store.apply_actions(
                    [completed], [("user", "我们已经到三亚了")], "s5"
                ),
                1,
            )
            self.assertEqual(store.load()["records"][0]["status"], "completed")

    def test_complete_and_cancel_only_apply_to_open_plans(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NixiLifeMemoryStore(Path(temp), "7", "nixi-family")
            store.apply_actions(
                [action(kind="event", status="completed")],
                [("user", "今晚我们一起吃了晚饭")],
                "event",
            )
            target = store.load()["records"][0]["id"]
            invalid_completion = action(
                operation="complete",
                target_id=target,
                kind="event",
                status="completed",
                content="重复完成一条已经发生的事件",
                evidence_quote="这件事完成了",
            )
            self.assertEqual(
                store.apply_actions(
                    [invalid_completion], [("user", "这件事完成了")], "invalid"
                ),
                0,
            )
            self.assertEqual(store.load()["records"][0]["status"], "completed")

    def test_user_acceptance_can_promote_an_existing_pending_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            store = NixiLifeMemoryStore(Path(temp), "7", "nixi-family")
            store.apply_actions(
                [
                    action(
                        kind="plan",
                        status="pending",
                        content="池骋提议九月五日带女儿去三亚",
                        evidence_role="assistant",
                        evidence_quote="九月五日带你去三亚",
                    )
                ],
                [("assistant", "九月五日带你去三亚")],
                "proposal",
            )
            target = store.load()["records"][0]["id"]
            accepted = action(
                operation="correct",
                target_id=target,
                kind="plan",
                status="planned",
                content="三人约定九月五日去三亚",
                evidence_quote="好，九月五日一起去三亚",
                event_at="2026-09-05T08:00:00+08:00",
            )
            self.assertEqual(
                store.apply_actions(
                    [accepted], [("user", "好，九月五日一起去三亚")], "accepted"
                ),
                1,
            )
            records = store.load()["records"]
            self.assertEqual(records[0]["status"], "superseded")
            self.assertEqual(records[1]["status"], "planned")
            self.assertEqual(records[1]["supersedes_id"], target)


class NixiLifeMemoryProviderTests(unittest.TestCase):
    def setUp(self):
        # Other isolated provider tests install deliberately tiny logger stubs in
        # sys.modules.  Pin this module's logger so discovery order cannot change
        # the result of the memory tests.
        nixi_memory_module.logger = _Logger()

    def provider(self, temp, mode, response=None):
        provider = MemoryProvider(
            {"storage_dir": temp, "max_context_records": 60}, None
        )
        provider.init_memory(
            role_id="device-a",
            llm=_FakeLLM(response or {"actions": []}),
            nixi_life_context={
                "owner_id": "42",
                "universe_id": "nixi-family",
                "mode": mode,
                "agent_id": f"agent-{mode}",
            },
        )
        return provider

    def test_three_modes_share_family_records_but_private_memory_is_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            wu = self.provider(temp, "wu")
            shared = action()
            private = action(
                kind="user_fact",
                status="active",
                visibility="wu_private",
                content="女儿只告诉吴所畏她准备换工作",
                event_at=None,
                evidence_quote="这件事先只告诉吴爸，我准备换工作",
            )
            wu.store.apply_actions(
                [shared, private],
                [
                    ("user", "今晚我们一起吃了晚饭"),
                    ("user", "这件事先只告诉吴爸，我准备换工作"),
                ],
                "s6",
            )

            chi = self.provider(temp, "chi")
            duo = self.provider(temp, "duo")
            wu_context = asyncio.run(wu.query_memory("工作晚饭"))
            chi_context = asyncio.run(chi.query_memory("工作晚饭"))
            duo_context = asyncio.run(duo.query_memory("工作晚饭"))
            self.assertIn("一起吃了晚饭", wu_context)
            self.assertIn("一起吃了晚饭", chi_context)
            self.assertIn("一起吃了晚饭", duo_context)
            self.assertIn("准备换工作", wu_context)
            self.assertNotIn("准备换工作", chi_context)
            self.assertNotIn("准备换工作", duo_context)

    def test_provider_extracts_and_saves_validated_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = self.provider(temp, "wu", {"actions": [action()]})
            result = asyncio.run(
                provider.save_memory(
                    [Message(role="user", content="今晚我们一起吃了晚饭")],
                    "s7",
                )
            )
            self.assertEqual(result, 1)
            self.assertEqual(len(provider.store.load()["records"]), 1)

    def test_each_mode_can_only_write_its_own_visibility_scope(self):
        attempts = (
            ("wu", "chi_private"),
            ("chi", "wu_private"),
            ("duo", "wu_private"),
            ("duo", "chi_private"),
        )
        for mode, visibility in attempts:
            with self.subTest(mode=mode, visibility=visibility):
                with tempfile.TemporaryDirectory() as temp:
                    forbidden = action(visibility=visibility)
                    provider = self.provider(temp, mode, {"actions": [forbidden]})
                    result = asyncio.run(
                        provider.save_memory(
                            [Message(role="user", content="今晚我们一起吃了晚饭")],
                            "visibility-test",
                        )
                    )
                    self.assertEqual(result, 0)
                    self.assertEqual(provider.store.load()["records"], [])

    def test_private_catalog_and_update_targets_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp:
            chi = self.provider(temp, "chi")
            private = action(
                kind="user_fact",
                status="active",
                visibility="chi_private",
                content="女儿只告诉池骋她准备搬家",
                event_at=None,
                evidence_quote="这件事只告诉池爸，我准备搬家",
            )
            chi.store.apply_actions(
                [private], [("user", "这件事只告诉池爸，我准备搬家")], "private"
            )
            target = chi.store.load()["records"][0]["id"]

            attempted_update = action(
                operation="correct",
                target_id=target,
                kind="user_fact",
                status="active",
                visibility="wu_private",
                content="女儿已经不准备搬家",
                event_at=None,
                evidence_quote="我不准备搬家了",
            )
            wu = self.provider(temp, "wu", {"actions": [attempted_update]})
            self.assertNotIn("准备搬家", wu._catalog_for_extractor())
            self.assertEqual(
                asyncio.run(
                    wu.save_memory(
                        [Message(role="user", content="我不准备搬家了")],
                        "cross-private-update",
                    )
                ),
                0,
            )
            records = chi.store.load()["records"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "active")

    def test_provider_without_authorized_nixi_context_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = MemoryProvider({"storage_dir": temp}, None)
            provider.init_memory(
                role_id="device-a",
                llm=_FakeLLM({"actions": [action()]}),
                nixi_life_context=None,
            )
            self.assertFalse(provider.enabled)
            self.assertEqual(asyncio.run(provider.query_memory("晚饭")), "")
            result = asyncio.run(
                provider.save_memory(
                    [Message(role="user", content="今晚我们一起吃了晚饭")],
                    "disabled-test",
                )
            )
            self.assertIsNone(result)
            self.assertFalse(any(Path(temp).rglob("*.json")))


if __name__ == "__main__":
    unittest.main()
