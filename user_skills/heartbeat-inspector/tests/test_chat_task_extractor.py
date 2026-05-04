#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from unittest.mock import patch

from scripts import chat_task_extractor as ext


class TestChatTaskExtractor(unittest.TestCase):
    def test_ensure_task_name_bracketed(self):
        self.assertEqual(ext._ensure_task_name_bracketed("确认 A（周五）"), "【确认 A（周五）】")
        self.assertEqual(ext._ensure_task_name_bracketed("【确认 A（周五）】"), "【确认 A（周五）】")

    def test_relative_time_anchoring_in_due_time(self):
        # due_time="下班前" should anchor to same day 19:00 based on create_time
        task = {
            "is_task": True,
            "task_name": "【整理方案（下班前）】",
            "summary": "【整理方案（下班前）】",
            "owners": ["张三"],
            "due_time": "下班前",
            "source_message_ids": ["m1"],
        }
        source_messages_full = [
            {
                "message_id": "m1",
                "sender": "李四",
                "chat_name": "群聊",
                "create_time": "2026-05-01T10:00:00+08:00",
                "text": "@张三 【整理方案（下班前）】",
            }
        ]

        out = ext._postprocess_task(task=task, source_messages_full=source_messages_full)
        self.assertEqual(out["due_time"], "2026-05-01 19:00")

    def test_postprocess_adds_suggestion_reply_when_missing(self):
        task = {
            "is_task": True,
            "summary": "确认是否纳入抖音商家及招募标准（今早11点前）",
            "owners": [],
            "due_time": None,
        }
        source_messages_full = [
            {
                "message_id": "m1",
                "sender": "江家徵",
                "chat_name": "项目A沟通群",
                "create_time": "2026-05-01T00:00:00+08:00",
                "text": "@于奇楠 这个需要确认一下\n麻烦今天 11 点前给结论",
            }
        ]

        out = ext._postprocess_task(task=task, source_messages_full=source_messages_full)
        self.assertTrue(out["task_name"].startswith("【") and out["task_name"].endswith("】"))
        self.assertIn("负责人", out.get("suggestion_reply", ""))
        self.assertIn("DDL", out.get("suggestion_reply", ""))
        self.assertIn("【任务名称】", out.get("suggestion_reply", ""))
        self.assertIn("\n", out.get("source_text_full", ""))

    def test_anchor_message_skips_llm_and_inherits_name(self):
        messages = [
            {
                "message_id": "m1",
                "create_time": "2026-05-01T10:00:00+08:00",
                "sender_name": "A",
                "content": "大家看下文档，【审阅SKM和HIPO商家权益一页纸并定稿（明日会前）】@全体",
            },
            {
                "message_id": "m2",
                "create_time": "2026-05-01T10:01:00+08:00",
                "sender_name": "全体成员",
                "content": "收到",
            },
        ]

        with patch.object(ext, "_call_llm_json", side_effect=AssertionError("llm should not be called")):
            tasks = ext.extract_tasks_from_chat_messages(chat_title="群聊", messages=messages, new_message_ids=["m1"])

        self.assertEqual(len(tasks), 1)
        t0 = tasks[0]
        self.assertEqual(t0["task_name"], "【审阅SKM和HIPO商家权益一页纸并定稿（明日会前）】")
        self.assertIn("锚点", "".join(t0.get("evidence", [])))
        self.assertTrue("全体成员" in t0.get("owners", []) or "全体" in t0.get("owners", []))

    def test_ack_lock_pending(self):
        messages = [
            {
                "message_id": "m1",
                "create_time": "2026-05-01T10:00:00+08:00",
                "sender_name": "A",
                "content": "@张三 【整理文档并定稿（下班前）】",
            },
            {
                "message_id": "m2",
                "create_time": "2026-05-01T10:10:00+08:00",
                "sender_name": "李四",
                "content": "我来看看",
            },
        ]

        with patch.object(ext, "_call_llm_json", return_value={"tasks": []}):
            tasks = ext.extract_tasks_from_chat_messages(chat_title="群聊", messages=messages, new_message_ids=["m1"])

        # Anchor path should produce one task.
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["ack_lock"]["status"], "pending")
        self.assertIn("⚠️", tasks[0]["ack_lock"]["tag"])

    def test_ack_lock_acked(self):
        messages = [
            {
                "message_id": "m1",
                "create_time": "2026-05-01T10:00:00+08:00",
                "sender_name": "A",
                "content": "@张三 【整理文档并定稿（下班前）】",
            },
            {
                "message_id": "m2",
                "create_time": "2026-05-01T10:10:00+08:00",
                "sender_name": "张三",
                "content": "收到",
            },
        ]

        with patch.object(ext, "_call_llm_json", return_value={"tasks": []}):
            tasks = ext.extract_tasks_from_chat_messages(chat_title="群聊", messages=messages, new_message_ids=["m1"])

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["ack_lock"]["status"], "acked")

    def test_status_trigger_extract(self):
        view_messages = [
            {
                "message_id": "m3",
                "create_time": "2026-05-01T11:00:00+08:00",
                "sender": "张三",
                "text": "【整理文档并定稿（下班前）】 /done",
            }
        ]

        updates = ext.extract_status_updates_from_messages(
            view_messages=view_messages,
            known_task_names=["【整理文档并定稿（下班前）】"],
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["new_status"], "done")

    def test_llm_task_name_overridden_by_anchor_in_source(self):
        messages = [
            {
                "message_id": "m1",
                "create_time": "2026-05-01T10:00:00+08:00",
                "sender_name": "A",
                "content": "【原始任务名】 @张三",
            }
        ]

        mocked_llm = {
            "tasks": [
                {
                    "is_task": True,
                    "task_name": "【改写后的任务名】",
                    "summary": "【改写后的任务名】",
                    "owners": ["张三"],
                    "due_time": "明早",
                    "source_message_ids": ["m1"],
                }
            ]
        }

        with patch.object(ext, "_call_llm_json", return_value=mocked_llm):
            tasks = ext.extract_tasks_from_chat_messages(chat_title="群聊", messages=messages, new_message_ids=["m1"])

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["task_name"], "【原始任务名】")

    def test_extract_tasks_overrides_source_fields(self):
        messages = [
            {"message_id": "m1", "create_time": "2026-05-01T10:00:00+08:00", "sender_name": "A", "content": "hello"},
            {"message_id": "m2", "create_time": "2026-05-01T10:01:00+08:00", "sender_name": "B", "content": "line1\nline2"},
        ]
        new_ids = ["m2"]

        mocked_llm = {
            "tasks": [
                {
                    "is_task": True,
                    "task_name": "确认事项（周五）",
                    "summary": "确认事项（周五）",
                    "owners": ["大家"],
                    "due_time": "周五",
                    "source_message_ids": ["m2"],
                    "source_text_full": "SHOULD_BE_OVERRIDDEN",
                    "source_messages_full": [],
                }
            ]
        }

        with patch.object(ext, "_call_llm_json", return_value=mocked_llm):
            tasks = ext.extract_tasks_from_chat_messages(chat_title="群聊", messages=messages, new_message_ids=new_ids)

        self.assertEqual(len(tasks), 1)
        t0 = tasks[0]
        self.assertEqual(t0["source_messages_full"][0]["message_id"], "m2")
        self.assertEqual(t0["source_messages_full"][0]["text"], "line1\nline2")
        self.assertEqual(t0["source_text_full"], "line1\nline2")
        self.assertTrue(t0["task_name"].startswith("【") and t0["task_name"].endswith("】"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
