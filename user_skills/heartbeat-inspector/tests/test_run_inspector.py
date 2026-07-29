#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.heartbeat_config import Target
from scripts import run_inspector as inspector


class TestWorkspaceRootResolution(unittest.TestCase):
    def test_workspace_root_falls_back_from_file_location(self):
        expected = Path(__file__).resolve().parents[3]
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(inspector._workspace_root(), expected)

    def test_bytedcli_auth_uses_workspace_root_script_path(self):
        expected = inspector._workspace_root() / "inner_skills" / "bytedcli-auth" / "scripts" / "bytedcli_auth.sh"
        calls = []

        def fake_run(cmd, timeout=60):
            calls.append((cmd, timeout))
            return '{"status":"success"}'

        with patch.object(inspector, "_run_cmd", side_effect=fake_run), patch.dict(os.environ, {}, clear=True):
            self.assertTrue(inspector._try_bytedcli_auth(verbose=False, dlq_path=Path(".heartbeat_dlq.jsonl")))

        self.assertEqual(calls[0][0], ["bash", str(expected)])


class TestMentionSearchRoute(unittest.TestCase):
    def test_relative_time_to_iso_window_supports_dynamic_units(self):
        window = inspector._relative_time_to_iso_window("last_2_weeks")
        self.assertIn("start", window)
        self.assertIn("end", window)
        self.assertRegex(window["start"], r"T")
        self.assertRegex(window["end"], r"T")

    def test_fetch_feishu_mentions_global_uses_lark_cli_messages_search(self):
        calls = []

        def fake_run(cmd, timeout=120):
            calls.append((cmd, timeout))
            return json.dumps({"data": {"items": [{"message_id": "m_cli"}]}})

        with patch.object(inspector, "_run_cmd", side_effect=fake_run):
            msgs = inspector.fetch_feishu_mentions_global(relative_time="last_6_hours", page_size=10)

        self.assertEqual(msgs, [{"message_id": "m_cli"}])
        self.assertEqual(calls[0][0][:5], ["lark-cli", "im", "+messages-search", "--chat-type", "group"])
        self.assertIn("--is-at-me", calls[0][0])
        self.assertIn("--as", calls[0][0])
        self.assertIn("user", calls[0][0])


class TestRunInspectorOutputLinks(unittest.TestCase):
    def _run_main(self):
        buf = io.StringIO()
        with redirect_stdout(buf), patch("sys.argv", ["run_inspector.py"]):
            rc = inspector.main()
        self.assertEqual(rc, 0)
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        return [json.loads(ln) for ln in lines]

    def test_feishu_chat_events_include_chat_name_and_links(self):
        target = Target(
            id="chat_t",
            type="feishu_chat",
            title="项目A沟通群",
            raw={"chat_name": "项目A沟通群"},
        )
        message = {
            "message_id": "m1",
            "sender_name": "张三",
            "create_time": "2026-05-01T10:00:00+08:00",
            "content": "请处理一下",
            "chat_id": "oc_chat_1",
            "chat_name": "项目A沟通群",
            "message_link": "https://example.com/message/m1",
        }
        task = {
            "task_name": "【跟进排期】",
            "source_text_full": "请处理一下",
            "source_messages_full": [
                {
                    "message_id": "m1",
                    "chat_id": "oc_chat_1",
                    "chat_name": "项目A沟通群",
                    "chat_link": "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_1",
                    "message_link": "https://example.com/message/m1",
                    "jump_link": "https://example.com/message/m1",
                    "text": "请处理一下",
                }
            ],
        }
        status_update = {
            "task_name": "【跟进排期】",
            "new_status": "done",
            "message_id": "m1",
            "chat_id": "oc_chat_1",
            "chat_name": "项目A沟通群",
            "chat_link": "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_1",
            "message_link": "https://example.com/message/m1",
            "jump_link": "https://example.com/message/m1",
            "source_text_full": "请处理一下 /done",
        }

        with (
            patch.object(inspector, "_try_bytedcli_auth", return_value=False),
            patch.object(inspector, "load_heartbeat_config", return_value={"version": 1, "targets": []}),
            patch.object(inspector, "validate_and_normalize_config", return_value=[target]),
            patch.object(inspector, "load_state", return_value={"runtime_cache": {}, "targets": {"chat_t": {"last_seen_message_id": "old"}}}),
            patch.object(inspector, "_load_chat_registry", return_value={"oc_chat_1": "项目A沟通群"}),
            patch.object(inspector, "save_state"),
            patch.object(inspector, "_resolve_chat_id", return_value="oc_chat_1"),
            patch.object(inspector, "fetch_feishu_chat_messages", return_value=[message]),
            patch.object(inspector, "diff_feishu_messages", return_value=([message], {"last_seen_message_id": "m1"})),
            patch.object(inspector, "extract_tasks_from_chat_messages", return_value=[task]),
            patch.object(inspector, "extract_status_updates_from_messages", return_value=[status_update]),
        ):
            events = self._run_main()

        self.assertEqual([event["type"] for event in events], ["chat_message_new", "chat_task", "task_status_update"])
        for event in events:
            self.assertEqual(event["chat_name"], "项目A沟通群")
            self.assertEqual(
                event["chat_link"],
                "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_1",
            )
            self.assertEqual(event["jump_link"], "https://example.com/message/m1")
        self.assertEqual(events[0]["message_link"], "https://example.com/message/m1")
        self.assertEqual(events[1]["message_id"], "m1")
        self.assertEqual(events[2]["message_id"], "m1")

    def test_feishu_mentions_events_include_chat_name_and_links(self):
        target = Target(
            id="mention_t",
            type="feishu_mentions_global",
            title="全局@我",
            raw={},
        )
        message = {
            "message_id": "m2",
            "sender_name": "李四",
            "create_time": "2026-05-01T11:00:00+08:00",
            "content": "@我 请今天处理",
            "chat_id": "oc_chat_2",
            "chat_name": "项目B沟通群",
            "chat_link": "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_2",
            "message_link": "https://example.com/message/m2",
            "jump_link": "https://example.com/message/m2",
        }
        task = {
            "task_name": "【今天处理】",
            "source_text_full": "@我 请今天处理",
            "source_messages_full": [
                {
                    "message_id": "m2",
                    "chat_id": "oc_chat_2",
                    "chat_name": "项目B沟通群",
                    "chat_link": "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_2",
                    "message_link": "https://example.com/message/m2",
                    "jump_link": "https://example.com/message/m2",
                    "text": "@我 请今天处理",
                }
            ],
        }
        status_update = {
            "task_name": "【今天处理】",
            "new_status": "blocked",
            "message_id": "m2",
            "chat_id": "oc_chat_2",
            "chat_name": "项目B沟通群",
            "chat_link": "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_2",
            "message_link": "https://example.com/message/m2",
            "jump_link": "https://example.com/message/m2",
            "source_text_full": "@我 请今天处理 /阻塞",
        }

        with (
            patch.object(inspector, "_try_bytedcli_auth", return_value=False),
            patch.object(inspector, "load_heartbeat_config", return_value={"version": 1, "targets": []}),
            patch.object(inspector, "validate_and_normalize_config", return_value=[target]),
            patch.object(inspector, "load_state", return_value={"runtime_cache": {}, "targets": {"mention_t": {"last_seen_message_id": "old"}}}),
            patch.object(inspector, "_load_chat_registry", return_value={"oc_chat_2": "项目B沟通群"}),
            patch.object(inspector, "save_state"),
            patch.object(inspector, "_get_self_open_id", return_value="ou_self"),
            patch.object(inspector, "fetch_feishu_mentions_global", return_value=[message]),
            patch.object(inspector, "diff_feishu_messages", return_value=([message], {"last_seen_message_id": "m2"})),
            patch.object(inspector, "extract_tasks_from_chat_messages", return_value=[task]),
            patch.object(inspector, "extract_status_updates_from_messages", return_value=[status_update]),
        ):
            events = self._run_main()

        self.assertEqual([event["type"] for event in events], ["mention_message_new", "chat_task", "task_status_update"])
        for event in events:
            self.assertEqual(event["chat_name"], "项目B沟通群")
            self.assertEqual(event["chat_id"], "oc_chat_2")
            self.assertEqual(
                event["chat_link"],
                "https://applink.larkoffice.com/client/chat/open?openChatId=oc_chat_2",
            )
            self.assertEqual(event["message_link"], "https://example.com/message/m2")
            self.assertEqual(event["jump_link"], "https://example.com/message/m2")

    def test_feishu_mentions_recovers_missing_chat_id_by_message_lookup(self):
        target = Target(
            id="mention_t",
            type="feishu_mentions_global",
            title="全局@我",
            raw={},
        )
        message = {
            "message_id": "m_lookup_chat",
            "sender_name": "江家徵",
            "create_time": "2026-07-03T17:25:00+08:00",
            "content": "@于奇楠 请跟进",
        }

        with (
            patch.object(inspector, "_try_bytedcli_auth", return_value=False),
            patch.object(inspector, "load_heartbeat_config", return_value={"version": 1, "targets": []}),
            patch.object(inspector, "validate_and_normalize_config", return_value=[target]),
            patch.object(inspector, "load_state", return_value={"runtime_cache": {}, "targets": {"mention_t": {"last_seen_message_id": "old"}}}),
            patch.object(inspector, "_load_chat_registry", return_value={"oc_lookup": "真实项目群"}),
            patch.object(inspector, "save_state"),
            patch.object(inspector, "_get_self_open_id", return_value="ou_self"),
            patch.object(inspector, "fetch_feishu_mentions_global", return_value=[message]),
            patch.object(
                inspector,
                "_lookup_message_meta_by_id",
                return_value={
                    "chat_id": "oc_lookup",
                    "chat_link": "https://applink.larkoffice.com/client/chat/open?openChatId=oc_lookup",
                    "message_link": "https://applink.feishu.cn/client/thread/open?open_chat_id=oc_lookup",
                    "jump_link": "https://applink.feishu.cn/client/thread/open?open_chat_id=oc_lookup",
                },
            ),
            patch.object(inspector, "diff_feishu_messages", side_effect=lambda _prev, msgs: (msgs, {"last_seen_message_id": "m_lookup_chat"})),
            patch.object(inspector, "extract_tasks_from_chat_messages", return_value=[]),
            patch.object(inspector, "extract_status_updates_from_messages", return_value=[]),
        ):
            events = self._run_main()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "mention_message_new")
        self.assertEqual(events[0]["chat_id"], "oc_lookup")
        self.assertEqual(events[0]["chat_name"], "真实项目群")
        self.assertEqual(events[0]["message_link"], "https://applink.feishu.cn/client/thread/open?open_chat_id=oc_lookup")
        self.assertEqual(events[0]["jump_link"], "https://applink.feishu.cn/client/thread/open?open_chat_id=oc_lookup")

    def test_feishu_mentions_recovers_missing_chat_id_by_chat_name_lookup(self):
        target = Target(
            id="mention_t",
            type="feishu_mentions_global",
            title="全局@我",
            raw={},
        )
        message = {
            "message_id": "m_missing_chat",
            "sender_name": "李四",
            "create_time": "2026-06-28T11:00:00+08:00",
            "content": "@我 请处理 chat_id 断链",
            "chat_name": "真实项目群",
            "message_link": "https://example.com/message/m_missing_chat",
        }

        with (
            patch.object(inspector, "_try_bytedcli_auth", return_value=False),
            patch.object(inspector, "load_heartbeat_config", return_value={"version": 1, "targets": []}),
            patch.object(inspector, "validate_and_normalize_config", return_value=[target]),
            patch.object(inspector, "load_state", return_value={"runtime_cache": {}, "targets": {"mention_t": {"last_seen_message_id": "old"}}}),
            patch.object(inspector, "_load_chat_registry", return_value={}),
            patch.object(inspector, "save_state"),
            patch.object(inspector, "_get_self_open_id", return_value="ou_self"),
            patch.object(inspector, "fetch_feishu_mentions_global", return_value=[message]),
            patch.object(inspector, "_search_chat_meta_by_name", return_value={"chat_id": "oc_recovered", "name": "真实项目群"}),
            patch.object(inspector, "diff_feishu_messages", side_effect=lambda _prev, msgs: (msgs, {"last_seen_message_id": "m_missing_chat"})),
            patch.object(inspector, "extract_tasks_from_chat_messages", return_value=[]),
            patch.object(inspector, "extract_status_updates_from_messages", return_value=[]),
        ):
            events = self._run_main()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "mention_message_new")
        self.assertEqual(events[0]["chat_id"], "oc_recovered")
        self.assertEqual(events[0]["chat_name"], "真实项目群")
        self.assertEqual(
            events[0]["chat_link"],
            "https://applink.larkoffice.com/client/chat/open?openChatId=oc_recovered",
        )

    def test_feishu_mentions_filters_broadcast_messages_but_still_advances_state(self):
        target = Target(
            id="mention_t",
            type="feishu_mentions_global",
            title="全局@我",
            raw={},
        )
        real_message = {
            "message_id": "m_real",
            "sender_name": "李四",
            "create_time": "2026-05-01T11:00:00+08:00",
            "content": "@于奇楠 请今天处理",
            "chat_id": "oc_chat_2",
            "chat_name": "项目B沟通群",
        }
        broadcast_message = {
            "message_id": "m_all",
            "sender_name": "王五",
            "create_time": "2026-05-01T11:05:00+08:00",
            "content": "@_all 大家知悉一下",
            "chat_id": "oc_chat_2",
            "chat_name": "项目B沟通群",
        }
        saved_states = []

        with (
            patch.object(inspector, "_try_bytedcli_auth", return_value=False),
            patch.object(inspector, "load_heartbeat_config", return_value={"version": 1, "targets": []}),
            patch.object(inspector, "validate_and_normalize_config", return_value=[target]),
            patch.object(inspector, "load_state", return_value={"runtime_cache": {}, "targets": {"mention_t": {"last_seen_message_id": "old"}}}),
            patch.object(inspector, "save_state", side_effect=lambda _path, state: saved_states.append(state)),
            patch.object(inspector, "_get_self_open_id", return_value="ou_self"),
            patch.object(inspector, "fetch_feishu_mentions_global", return_value=[real_message, broadcast_message]),
            patch.object(inspector, "extract_tasks_from_chat_messages", return_value=[]),
            patch.object(inspector, "extract_status_updates_from_messages", return_value=[]),
        ):
            events = self._run_main()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message_id"], "m_real")
        self.assertEqual(events[0]["type"], "mention_message_new")
        self.assertTrue(saved_states)
        self.assertEqual(saved_states[-1]["targets"]["mention_t"]["last_seen_message_id"], "m_all")

    def test_feishu_mentions_filters_system_broadcast_messages(self):
        target = Target(
            id="mention_t",
            type="feishu_mentions_global",
            title="全局@我",
            raw={},
        )
        system_message = {
            "message_id": "m_sys",
            "sender_name": "系统广播",
            "create_time": "2026-05-01T11:00:00+08:00",
            "content": "请关注系统通知",
            "chat_id": "oc_chat_3",
            "chat_name": "系统群",
        }
        saved_states = []

        with (
            patch.object(inspector, "_try_bytedcli_auth", return_value=False),
            patch.object(inspector, "load_heartbeat_config", return_value={"version": 1, "targets": []}),
            patch.object(inspector, "validate_and_normalize_config", return_value=[target]),
            patch.object(inspector, "load_state", return_value={"runtime_cache": {}, "targets": {"mention_t": {"last_seen_message_id": "old"}}}),
            patch.object(inspector, "save_state", side_effect=lambda _path, state: saved_states.append(state)),
            patch.object(inspector, "_get_self_open_id", return_value="ou_self"),
            patch.object(inspector, "fetch_feishu_mentions_global", return_value=[system_message]),
            patch.object(inspector, "extract_tasks_from_chat_messages", return_value=[]),
            patch.object(inspector, "extract_status_updates_from_messages", return_value=[]),
        ):
            events = self._run_main()

        self.assertEqual(events, [])
        self.assertTrue(saved_states)
        self.assertEqual(saved_states[-1]["targets"]["mention_t"]["last_seen_message_id"], "m_sys")


if __name__ == "__main__":
    unittest.main(verbosity=2)
