import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from task_flow_engine import taskflow_ack_sender as MODULE


class FakeResult:
    def __init__(self, *, success=True, data=None, data_error=None):
        self.success = success
        self._data = data
        self._data_error = data_error

    @property
    def data(self):
        if self._data_error is not None:
            raise self._data_error
        return self._data


class TestTaskflowAckSender(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(tempfile.mkdtemp(prefix="taskflow_ack_sender_"))
        self.temp_workspace = self.temp_root / "workspace"
        self.temp_repo = self.temp_workspace / "user_skills" / "task-flow-engine"
        self.temp_repo.mkdir(parents=True, exist_ok=True)
        self.log_path = self.temp_repo / "notification_logs" / "taskflow_ack_test.jsonl"

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _patch_paths(self):
        return (
            mock.patch.object(MODULE, "_workspace_root", return_value=self.temp_workspace),
            mock.patch.object(MODULE, "_repo_root", return_value=self.temp_repo),
        )

    def test_build_taskflow_ack_post_uses_single_sheet_link(self):
        payload = MODULE.build_taskflow_ack_post(
            task_name="研究 chinamaxxing",
            owner="@李京达",
        )
        row = payload["zh_cn"]["content"][0]
        self.assertEqual(len(row), 2)
        self.assertEqual(row[0]["tag"], "text")
        self.assertIn("已录入任务台账：研究 chinamaxxing", row[0]["text"])
        self.assertEqual(row[1]["tag"], "a")
        self.assertEqual(row[1]["href"], MODULE.DEFAULT_TASKFLOW_SHEET_URL)

    def test_send_taskflow_ack_skips_duplicate_source_message(self):
        sent_cards_path = self.temp_workspace / ".aime" / "log" / "sent_cards" / "SENT_CARDS.jsonl"
        sent_cards_path.parent.mkdir(parents=True, exist_ok=True)
        sent_cards_path.write_text(
            json.dumps(
                {
                    "logical_msg_id": "task-flow-engine|taskflow_ack|existing",
                    "topic": "taskflow_ack",
                    "run_id": "existing_run",
                    "receiver": {"chat_id": "oc_test"},
                    "message_id": "om_existing",
                    "result": "success",
                    "source_message_id": "om_msg_123",
                    "sent_at": MODULE._now_iso(),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        workspace_patch, repo_patch = self._patch_paths()
        with workspace_patch, repo_patch, mock.patch.object(MODULE, "call_aime_tool") as mocked_call:
            record = MODULE.send_taskflow_ack(
                chat_id="oc_test",
                source_message_id="om_msg_123",
                task_name="任务A",
                owner_text="@张三",
                notification_log_path=self.log_path,
            )

        self.assertEqual(record["result"], "skipped_duplicate_source_message")
        self.assertEqual(record["duplicate_of"]["message_id"], "om_existing")
        mocked_call.assert_not_called()
        log_lines = self.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log_lines), 1)

    def test_send_taskflow_ack_treats_success_as_success_even_when_data_parse_fails(self):
        fake_result = FakeResult(success=True, data_error=RuntimeError("cannot read data"))
        workspace_patch, repo_patch = self._patch_paths()
        with workspace_patch, repo_patch, mock.patch.object(MODULE, "call_aime_tool", return_value=fake_result):
            record = MODULE.send_taskflow_ack(
                chat_id="oc_test",
                source_message_id="om_msg_456",
                task_name="任务B",
                owner_text="@李四",
                notification_log_path=self.log_path,
            )

        self.assertEqual(record["result"], "success")
        self.assertIn("读取 data 失败", record["parse_warning"])
        sent_cards_path = self.temp_workspace / ".aime" / "log" / "sent_cards" / "SENT_CARDS.jsonl"
        sent_records = [json.loads(line) for line in sent_cards_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(sent_records), 1)
        self.assertEqual(sent_records[0]["source_message_id"], "om_msg_456")
        self.assertEqual(sent_records[0]["result"], "success")

    def test_send_taskflow_ack_extracts_message_ids_from_payload(self):
        fake_result = FakeResult(
            success=True,
            data={
                "message_id": "om_new",
                "open_message_id": "open_new",
                "status": "success",
            },
        )
        workspace_patch, repo_patch = self._patch_paths()
        with workspace_patch, repo_patch, \
            mock.patch.object(MODULE, "call_aime_tool", return_value=fake_result) as mocked_call, \
            mock.patch.object(MODULE, "probe_taskflow_thread_attachment", return_value={"status": "verified_same_thread", "source_thread_id": "omt_1", "reply_thread_id": "omt_1"}) as mocked_probe:
            record = MODULE.send_taskflow_ack(
                chat_id="oc_test",
                source_message_id="om_msg_789",
                task_name="任务C",
                owner_text="@王五",
                notification_log_path=self.log_path,
            )

        self.assertEqual(record["result"], "success")
        self.assertEqual(record["message_id"], "om_new")
        self.assertEqual(record["open_message_id"], "open_new")
        self.assertEqual(record["thread_probe"]["status"], "verified_same_thread")
        mocked_probe.assert_called_once_with(source_message_id="om_msg_789", reply_message_id="om_new")
        mocked_call.assert_called_once_with(
            "lark_im_message",
            "lark_im_reply_message",
            {
                "message_id": "om_msg_789",
                "content": mock.ANY,
                "content_type": "post",
                "reply_in_thread": True,
            },
        )

    def test_send_taskflow_ack_marks_probe_failure(self):
        fake_result = FakeResult(
            success=True,
            data={
                "message_id": "om_probe_failed",
                "status": "success",
            },
        )
        workspace_patch, repo_patch = self._patch_paths()
        with workspace_patch, repo_patch, \
            mock.patch.object(MODULE, "call_aime_tool", return_value=fake_result), \
            mock.patch.object(MODULE, "probe_taskflow_thread_attachment", return_value={"status": "thread_mismatch", "source_thread_id": "omt_a", "reply_thread_id": "omt_b"}):
            record = MODULE.send_taskflow_ack(
                chat_id="oc_test",
                source_message_id="om_msg_probe",
                task_name="任务Probe",
                owner_text="@探针",
                notification_log_path=self.log_path,
            )

        self.assertEqual(record["result"], "failed_thread_probe")
        self.assertEqual(record["error"], "thread_probe_failed:thread_mismatch")
        self.assertEqual(record["thread_probe"]["status"], "thread_mismatch")

    def test_send_taskflow_ack_rejects_non_feishu_message_id(self):
        workspace_patch, repo_patch = self._patch_paths()
        with workspace_patch, repo_patch:
            with self.assertRaisesRegex(ValueError, "必须包含 Feishu 原始 message_id"):
                MODULE.send_taskflow_ack(
                    chat_id="oc_test",
                    source_message_id="local_uuid_123",
                    task_name="任务D",
                    owner_text="@赵六",
                    notification_log_path=self.log_path,
                )

    def test_extract_source_message_id_accepts_all_taskflow_entry_shapes(self):
        cases = [
            "om_direct",
            {"source_message_id": "om_source"},
            {"feishu_om_id": "om_feishu"},
            {"event": {"message_id": "om_nested"}},
            '{"reply_to":"om_json"}',
        ]
        self.assertEqual(
            [MODULE.extract_source_message_id(case) for case in cases],
            ["om_direct", "om_source", "om_feishu", "om_nested", "om_json"],
        )

    def test_extract_source_message_id_rejects_local_ids(self):
        self.assertIsNone(MODULE.extract_source_message_id({"message_id": "local_uuid_123"}))
        with self.assertRaisesRegex(ValueError, "必须包含 Feishu 原始 message_id"):
            MODULE.require_source_message_id({"aime_uuid": "123e4567-e89b-12d3-a456-426614174000"})


if __name__ == "__main__":
    unittest.main()
