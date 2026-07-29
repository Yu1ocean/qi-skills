import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "task_patrol_notify.py"
SPEC = importlib.util.spec_from_file_location("task_patrol_notify", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.path.insert(0, str(REPO_ROOT))
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestTaskPatrolNotify(unittest.TestCase):
    def setUp(self):
        tmp_root = REPO_ROOT / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="notify_test_", dir=str(tmp_root)))
        self.payload_paths = []

    def tearDown(self):
        for path in self.payload_paths:
            if path.exists():
                path.unlink()
            parent = path.parent
            while parent != REPO_ROOT and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _card(self, body: str) -> dict:
        return {
            "name": "AimeCard",
            "dsl": {
                "schema": "2.0",
                "header": {
                    "title": {"tag": "plain_text", "content": "任务巡检提醒"},
                    "template": "blue",
                },
                "body": {"elements": [{"tag": "markdown", "content": body}]},
            },
        }

    def _group_route(self, *, chat_id: str | None = None) -> dict:
        return {
            "target_chat": {"chat_id": chat_id or MODULE.DEFAULT_TARGET_CHAT_ID, "name": ""},
            "count": 1,
            "message": "群广播预览",
            "card": self._card("群广播内容"),
            "items": [],
        }

    def _run_main(self, alerts: dict, *extra_args: str):
        alerts_path = self.temp_dir / "alerts.json"
        log_path = self.temp_dir / "notify.jsonl"
        alerts_path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")

        argv = [
            "task_patrol_notify.py",
            "--alerts-file",
            str(alerts_path.relative_to(REPO_ROOT)),
            "--log-file",
            str(log_path.relative_to(REPO_ROOT)),
            *extra_args,
        ]
        with mock.patch.object(MODULE, "_sync_chat_registry_from_feishu", return_value=None):
            with mock.patch.object(sys, "argv", argv):
                exit_code = MODULE.main()

        records = []
        if log_path.exists():
            with log_path.open("r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    records.append(record)
                    payload_path = record.get("payload_path")
                    if payload_path:
                        self.payload_paths.append(REPO_ROOT / payload_path)
        return exit_code, records

    def test_enable_private_chat_prefers_p2p_routes(self):
        alerts = {
            "summary": {"today": "2026-05-08"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {
                    "alice@bytedance.com": {
                        "owner": {
                            "display_name": "Alice",
                            "raw": "Alice",
                            "email": "alice@bytedance.com",
                            "open_id": "ou_alice",
                            "source": "sheet_roster",
                        },
                        "count": 2,
                        "message": "Alice 个人异常预览",
                        "card": self._card("Alice 个人卡片"),
                        "items": [{"task": "任务A"}, {"task": "任务B"}],
                    }
                },
                "private": {},
            },
        }

        exit_code, records = self._run_main(alerts, "--dry-run", "--enable-private-chat")
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(records), 2)

        private_record = next(record for record in records if record["mode"] == "private")
        self.assertEqual(private_record["route_source"], "p2p")
        self.assertEqual(private_record["receiver"]["id_type"], "email")
        self.assertEqual(private_record["receiver"]["receiver_id"], "alice@bytedance.com")
        self.assertEqual(private_record["result"], "skipped_dry_run")
        self.assertTrue((REPO_ROOT / private_record["payload_path"]).exists())

    def test_private_chat_skips_when_only_open_id_available(self):
        alerts = {
            "summary": {"today": "2026-05-08"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {
                    "ou_only": {
                        "owner": {
                            "display_name": "只开了 OpenID",
                            "raw": "只开了 OpenID",
                            "open_id": "ou_only",
                            "source": "sheet_roster",
                        },
                        "count": 1,
                        "message": "OpenID-only 用户异常预览",
                        "card": self._card("OpenID-only 用户卡片"),
                        "items": [{"task": "任务C"}],
                    }
                },
                "private": {},
            },
        }

        exit_code, records = self._run_main(alerts, "--dry-run", "--enable-private-chat")
        self.assertEqual(exit_code, 0)

        private_record = next(record for record in records if record["mode"] == "private")
        self.assertEqual(private_record["result"], "skipped_missing_receiver")
        self.assertEqual(private_record["skip_reason"], "open_id_only_but_sender_does_not_support_open_id")
        self.assertTrue((REPO_ROOT / private_record["payload_path"]).exists())

    def test_private_chat_falls_back_to_routes_private_when_p2p_absent(self):
        alerts = {
            "summary": {"today": "2026-05-08"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {},
                "private": {
                    "bob@bytedance.com": {
                        "owner": {
                            "display_name": "Bob",
                            "raw": "Bob",
                            "email": "bob@bytedance.com",
                            "open_id": "ou_bob",
                            "source": "sheet_roster",
                        },
                        "count": 1,
                        "message": "Bob 私聊异常预览",
                        "card": self._card("Bob 个人卡片"),
                        "items": [{"task": "任务D"}],
                    }
                },
            },
        }

        exit_code, records = self._run_main(alerts, "--dry-run", "--enable-private-chat")
        self.assertEqual(exit_code, 0)

        private_record = next(record for record in records if record["mode"] == "private")
        self.assertEqual(private_record["route_source"], "private")
        self.assertEqual(private_record["receiver"]["receiver_id"], "bob@bytedance.com")
        self.assertEqual(private_record["result"], "skipped_dry_run")

    def test_group_broadcast_rejects_non_registry_chat_id(self):
        alerts = {
            "summary": {"today": "2026-05-08"},
            "routes": {
                "group_broadcast": self._group_route(chat_id="oc_other_chat"),
                "p2p": {},
                "private": {},
            },
        }

        with self.assertRaises(MODULE.ChatRegistryError):
            self._run_main(alerts, "--dry-run", "--target-chat-id", "oc_another_chat")

    def test_group_broadcast_defaults_to_dry_run_without_commit(self):
        alerts = {
            "summary": {"today": "2026-05-08"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {},
                "private": {},
            },
        }

        exit_code, records = self._run_main(alerts)
        self.assertEqual(exit_code, 0)
        group_record = next(record for record in records if record["mode"] == "group")
        self.assertEqual(group_record["receiver"]["chat_id"], MODULE.DEFAULT_TARGET_CHAT_ID)
        self.assertEqual(group_record["result"], "skipped_default_dry_run")

    def test_commit_group_broadcast_requires_confirmation(self):
        alerts = {
            "summary": {"today": "2026-05-08"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {},
                "private": {},
            },
        }

        with self.assertRaises(MODULE.ChatRegistryError):
            self._run_main(alerts, "--commit-group-broadcast")

    def test_find_recent_sent_card_matches_same_topic_and_chat(self):
        sent_cards_dir = MODULE._workspace_root() / ".aime" / "log" / "sent_cards"
        sent_cards_dir.mkdir(parents=True, exist_ok=True)
        sent_cards_path = sent_cards_dir / "SENT_CARDS.jsonl"
        backup_path = self.temp_dir / "SENT_CARDS.backup.jsonl"
        if sent_cards_path.exists():
            shutil.copy2(sent_cards_path, backup_path)
        try:
            now_iso = MODULE.datetime.now(MODULE.timezone.utc).isoformat()
            sent_cards_path.write_text(
                json.dumps(
                    {
                        "logical_msg_id": "task-flow-engine|group|20260508_095959",
                        "logical_topic_key": "task-flow-engine|group|2026-05-08",
                        "created_at": now_iso,
                        "sent_at": now_iso,
                        "receiver": {"chat_id": MODULE.DEFAULT_TARGET_CHAT_ID},
                        "result": "success",
                        "message_id": "om_existing",
                        "card_id": "card_existing",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            duplicate = MODULE._find_recent_sent_card(
                logical_topic_key="task-flow-engine|group|2026-05-08",
                receiver={"chat_id": MODULE.DEFAULT_TARGET_CHAT_ID},
            )
        finally:
            if backup_path.exists():
                shutil.copy2(backup_path, sent_cards_path)
            elif sent_cards_path.exists():
                sent_cards_path.unlink()

        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate["logical_topic_key"], "task-flow-engine|group|2026-05-08")
        self.assertEqual(duplicate.get("receiver", {}).get("chat_id"), MODULE.DEFAULT_TARGET_CHAT_ID)

    def test_find_recent_sent_card_matches_same_private_receiver_id(self):
        sent_cards_dir = MODULE._workspace_root() / ".aime" / "log" / "sent_cards"
        sent_cards_dir.mkdir(parents=True, exist_ok=True)
        sent_cards_path = sent_cards_dir / "SENT_CARDS.jsonl"
        backup_path = self.temp_dir / "SENT_CARDS.private.backup.jsonl"
        if sent_cards_path.exists():
            shutil.copy2(sent_cards_path, backup_path)
        try:
            now_iso = MODULE.datetime.now(MODULE.timezone.utc).isoformat()
            sent_cards_path.write_text(
                json.dumps(
                    {
                        "logical_msg_id": "task-flow-engine|private|20260508_095959",
                        "logical_topic_key": "task-flow-engine|private|2026-05-08",
                        "created_at": now_iso,
                        "sent_at": now_iso,
                        "receiver": {"receiver_id": "private_user@example.com", "id_type": "email"},
                        "result": "success",
                        "message_id": "om_private_existing",
                        "card_id": "card_private_existing",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            duplicate = MODULE._find_recent_sent_card(
                logical_topic_key="task-flow-engine|private|2026-05-08",
                receiver={"receiver_id": "private_user@example.com", "id_type": "email"},
            )
        finally:
            if backup_path.exists():
                shutil.copy2(backup_path, sent_cards_path)
            elif sent_cards_path.exists():
                sent_cards_path.unlink()

        self.assertIsNotNone(duplicate)
        self.assertEqual(duplicate["logical_topic_key"], "task-flow-engine|private|2026-05-08")
        self.assertEqual(duplicate.get("receiver", {}).get("receiver_id"), "private_user@example.com")

    def test_claim_delivery_guard_blocks_same_group_topic_and_receiver(self):
        receiver = {"chat_id": MODULE.DEFAULT_TARGET_CHAT_ID}
        guard_root = MODULE._delivery_guard_root()
        if guard_root.exists():
            shutil.rmtree(guard_root)
        try:
            claimed, existing = MODULE._claim_delivery_guard(
                logical_topic_key="task-flow-engine|group|2026-05-08",
                receiver=receiver,
                run_id="20260508_100000",
            )
            self.assertTrue(claimed)
            self.assertIsNone(existing)

            claimed_again, existing_again = MODULE._claim_delivery_guard(
                logical_topic_key="task-flow-engine|group|2026-05-08",
                receiver=receiver,
                run_id="20260508_100001",
            )
            self.assertFalse(claimed_again)
            self.assertIsInstance(existing_again, dict)
            self.assertEqual(existing_again.get("status"), "sending")
        finally:
            shutil.rmtree(guard_root, ignore_errors=True)

    def test_release_delivery_guard_writes_receipt_and_future_claim_is_blocked(self):
        receiver = {"chat_id": MODULE.DEFAULT_TARGET_CHAT_ID}
        guard_root = MODULE._delivery_guard_root()
        if guard_root.exists():
            shutil.rmtree(guard_root)
        try:
            claimed, _ = MODULE._claim_delivery_guard(
                logical_topic_key="task-flow-engine|group|2026-05-08",
                receiver=receiver,
                run_id="20260508_100000",
            )
            self.assertTrue(claimed)
            record = {
                "run_id": "20260508_100000",
                "created_at": MODULE.datetime.now(MODULE.timezone.utc).isoformat(),
                "sent_at": MODULE.datetime.now(MODULE.timezone.utc).isoformat(),
                "result": "success",
                "message_id": "om_existing",
                "card_id": "card_existing",
                "logical_msg_id": "task-flow-engine|group|20260508_100000",
            }
            MODULE._release_delivery_guard(
                logical_topic_key="task-flow-engine|group|2026-05-08",
                receiver=receiver,
                record=record,
                success=True,
            )

            claimed_again, existing_again = MODULE._claim_delivery_guard(
                logical_topic_key="task-flow-engine|group|2026-05-08",
                receiver=receiver,
                run_id="20260508_100001",
            )
            self.assertFalse(claimed_again)
            self.assertEqual(existing_again.get("message_id"), "om_existing")
        finally:
            shutil.rmtree(guard_root, ignore_errors=True)

    def test_group_dry_run_builds_visual_card_with_top3_and_stats_image(self):
        alerts = {
            "summary": {
                "today": "2026-05-11",
                "total_findings": 7,
                "counts": {"已超期": 2, "临近到期": 1, "缺失 DDL": 3, "格式异常": 1},
            },
            "grouped_results": {
                "已超期": [
                    {
                        "key": "1",
                        "task": "任务A",
                        "alert_category": "已超期",
                        "issue_type": "overdue",
                        "owners": [{"display_name": "夏春雨", "raw": "夏春雨", "open_id": "ou_xia", "email": "xia@bytedance.com"}],
                    },
                    {
                        "key": "2",
                        "task": "任务B",
                        "alert_category": "已超期",
                        "issue_type": "overdue",
                        "owners": [{"display_name": "于奇楠", "raw": "于奇楠", "open_id": "ou_yu", "email": "yu@bytedance.com"}],
                    },
                ],
                "临近到期": [
                    {
                        "key": "2b",
                        "task": "任务B-临近",
                        "alert_category": "临近到期",
                        "issue_type": "due_soon",
                        "owners": [{"display_name": "于奇楠", "raw": "于奇楠", "open_id": "ou_yu", "email": "yu@bytedance.com"}],
                    }
                ],
                "缺失 DDL": [
                    {
                        "key": "3",
                        "task": "任务C",
                        "alert_category": "缺失 DDL",
                        "issue_type": "missing_ddl",
                        "owners": [{"display_name": "夏春雨", "raw": "夏春雨", "open_id": "ou_xia", "email": "xia@bytedance.com"}],
                    },
                    {
                        "key": "4",
                        "task": "任务D",
                        "alert_category": "缺失 DDL",
                        "issue_type": "missing_ddl",
                        "owners": [{"display_name": "赵月晨", "raw": "赵月晨", "open_id": "ou_zhao", "email": "zhao@bytedance.com"}],
                    },
                    {
                        "key": "5",
                        "task": "任务E",
                        "alert_category": "缺失 DDL",
                        "issue_type": "missing_ddl",
                        "owners": [{"display_name": "赵月晨", "raw": "赵月晨", "open_id": "ou_zhao", "email": "zhao@bytedance.com"}],
                    },
                ],
                "格式异常": [
                    {
                        "key": "6",
                        "task": "任务F",
                        "alert_category": "格式异常",
                        "issue_type": "format_error",
                        "owners": [{"display_name": "夏春雨", "raw": "夏春雨", "open_id": "ou_xia", "email": "xia@bytedance.com"}],
                    }
                ],
            },
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {},
                "private": {},
            },
        }

        exit_code, records = self._run_main(alerts, "--dry-run")
        self.assertEqual(exit_code, 0)
        group_record = next(record for record in records if record["mode"] == "group")
        self.assertEqual(group_record["result"], "skipped_dry_run")
        self.assertTrue((REPO_ROOT / group_record["stats_image_path"]).exists())
        self.assertEqual([owner["display_name"] for owner in group_record["top_focus_owners"]], ["夏春雨", "于奇楠", "赵月晨"])
        self.assertEqual(group_record["summary_counts"], {"已超期": 2, "临近到期": 1, "缺失 DDL": 3, "格式异常": 1})

        payload_path = REPO_ROOT / group_record["payload_path"]
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        elements = payload["dsl"]["body"]["elements"]
        markdown_contents = [element.get("content", "") for element in elements if isinstance(element, dict)]
        self.assertTrue(any("**📌 重点关注**" in content or "重点关注跟进改进" in content for content in markdown_contents))
        self.assertTrue(any("🔵 **临近到期** 1" in content for content in markdown_contents))
        self.assertTrue(all("1. <at id=" not in content for content in markdown_contents))
        self.assertTrue(any("异常总览表" in content for content in markdown_contents))
        self.assertTrue(any("真实发送时会嵌入卡片正文" in content for content in markdown_contents))

    def test_build_visual_group_card_bundle_uploads_image_and_embeds_img_key(self):
        alerts = {
            "summary": {"today": "2026-05-11"},
            "grouped_results": {
                "已超期": [
                    {
                        "key": "1",
                        "task": "任务A",
                        "alert_category": "已超期",
                        "issue_type": "overdue",
                        "owners": [{"display_name": "夏春雨", "raw": "夏春雨", "open_id": "ou_xia", "email": "xia@bytedance.com"}],
                    }
                ],
                "临近到期": [
                    {
                        "key": "2",
                        "task": "任务B",
                        "alert_category": "临近到期",
                        "issue_type": "due_soon",
                        "owners": [{"display_name": "于奇楠", "raw": "于奇楠", "open_id": "ou_yu", "email": "yu@bytedance.com"}],
                    }
                ],
                "缺失 DDL": [],
                "格式异常": [],
            },
            "routes": {"group_broadcast": self._group_route(), "p2p": {}, "private": {}},
        }

        class FakeSender:
            def upload_image(self, *, image_path):
                self.image_path = image_path
                return MODULE.SendResult(
                    ok=True,
                    returncode=0,
                    stdout="",
                    stderr="",
                    parsed={"image_key": "img_uploaded_test"},
                )

        sender = FakeSender()
        bundle = MODULE._build_visual_group_card_bundle(alerts=alerts, payload_root=self.temp_dir, sender=sender)

        self.assertEqual(bundle["image_key"], "img_uploaded_test")
        self.assertTrue(bundle["image_path"].exists())
        img_element = next(element for element in bundle["payload"]["dsl"]["body"]["elements"] if element.get("tag") == "img")
        self.assertEqual(img_element["img_key"], "img_uploaded_test")

    def test_committed_group_broadcast_requires_run_daily_pipeline_entry(self):
        alerts = {
            "summary": {"today": "2099-01-01"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {},
                "private": {},
            },
        }

        with self.assertRaises(MODULE.ChatRegistryError):
            self._run_main(
                alerts,
                "--commit-group-broadcast",
                "--confirm-group-broadcast",
                "CONFIRM_GROUP_BROADCAST",
            )

    def test_main_skips_second_committed_group_broadcast_for_same_day_topic(self):
        alerts = {
            "summary": {"today": "2099-01-01"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {},
                "private": {},
            },
        }
        log_path = self.temp_dir / "notify.jsonl"
        send_calls = []

        def fake_send_payload(*, sender, payload_path, receiver_id, id_type, record, logger):
            send_calls.append({"receiver_id": receiver_id, "id_type": id_type, "payload_path": str(payload_path)})
            record.update(
                {
                    "sent_at": MODULE.datetime.now(MODULE.timezone.utc).isoformat(),
                    "result": "success",
                    "message_id": f"om_mock_{len(send_calls)}",
                    "logical_msg_id": f"task-flow-engine|group|mock_{len(send_calls)}",
                }
            )
            logger.append(record)
            return True

        with mock.patch.dict(os.environ, {MODULE.COMMITTED_SEND_ENTRY_ENV: MODULE.COMMITTED_SEND_ENTRY_VALUE}, clear=False):
            with mock.patch.object(MODULE, "_preflight_group_target", return_value={
                "chat_id": MODULE.DEFAULT_TARGET_CHAT_ID,
                "name": "UK/EU/JP POP BD",
            }):
                with mock.patch.object(MODULE, "_build_visual_group_card_bundle", return_value={
                    "payload": self._card("群广播内容"),
                    "top_focus_owners": [],
                    "summary_counts": {"已超期": 1},
                }):
                    with mock.patch.object(MODULE, "_send_payload", side_effect=fake_send_payload):
                        first_exit_code, first_records = self._run_main(
                            alerts,
                            "--commit-group-broadcast",
                            "--confirm-group-broadcast",
                            "CONFIRM_GROUP_BROADCAST",
                        )
                        self.assertEqual(first_exit_code, 0)
                        first_group_record = next(record for record in first_records if record["mode"] == "group")
                        self.assertEqual(first_group_record["result"], "success")
                        self.assertEqual(len(send_calls), 1)

                        if log_path.exists():
                            log_path.unlink()

                        second_exit_code, second_records = self._run_main(
                            alerts,
                            "--commit-group-broadcast",
                            "--confirm-group-broadcast",
                            "CONFIRM_GROUP_BROADCAST",
                        )

        self.assertEqual(second_exit_code, 0)
        second_group_record = next(record for record in second_records if record["mode"] == "group")
        self.assertEqual(second_group_record["result"], "skipped_duplicate_recent_send")
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(second_group_record["duplicate_of"]["message_id"], "om_mock_1")

    def test_group_success_with_private_failure_returns_zero_by_default(self):
        alerts = {
            "summary": {"today": "2099-01-02"},
            "routes": {
                "group_broadcast": self._group_route(),
                "p2p": {
                    "alice@bytedance.com": {
                        "owner": {
                            "display_name": "Alice",
                            "raw": "Alice",
                            "email": "alice@bytedance.com",
                            "open_id": "ou_alice",
                            "source": "sheet_roster",
                        },
                        "count": 1,
                        "message": "Alice 个人异常预览",
                        "card": self._card("Alice 个人卡片"),
                        "items": [{"task": "任务A"}],
                    }
                },
                "private": {},
            },
        }
        send_calls = []

        def fake_send_payload(*, sender, payload_path, receiver_id, id_type, record, logger):
            send_calls.append({"receiver_id": receiver_id, "mode": record.get("mode")})
            if record.get("mode") == "group":
                record.update(
                    {
                        "sent_at": MODULE.datetime.now(MODULE.timezone.utc).isoformat(),
                        "result": "success",
                        "message_id": "om_group_success",
                        "logical_msg_id": "task-flow-engine|group|mock_success",
                    }
                )
                logger.append(record)
                return True
            record.update(
                {
                    "sent_at": MODULE.datetime.now(MODULE.timezone.utc).isoformat(),
                    "result": "failed",
                    "error": "security policy: private send blocked",
                }
            )
            logger.append(record)
            return False

        with mock.patch.dict(os.environ, {MODULE.COMMITTED_SEND_ENTRY_ENV: MODULE.COMMITTED_SEND_ENTRY_VALUE}, clear=False):
            with mock.patch.object(MODULE, "_preflight_group_target", return_value={
                "chat_id": MODULE.DEFAULT_TARGET_CHAT_ID,
                "name": "UK/EU/JP POP BD",
            }):
                with mock.patch.object(MODULE, "_build_visual_group_card_bundle", return_value={
                    "payload": self._card("群广播内容"),
                    "top_focus_owners": [],
                    "summary_counts": {"已超期": 1},
                }):
                    with mock.patch.object(MODULE, "_send_payload", side_effect=fake_send_payload):
                        exit_code, records = self._run_main(
                            alerts,
                            "--enable-private-chat",
                            "--commit-group-broadcast",
                            "--confirm-group-broadcast",
                            "CONFIRM_GROUP_BROADCAST",
                        )

        self.assertEqual(exit_code, 0)
        self.assertEqual([call["mode"] for call in send_calls], ["group", "private"])
        meta_record = next(record for record in records if record["mode"] == "meta")
        self.assertEqual(meta_record["result"], "private_errors_ignored_after_group_success")


if __name__ == "__main__":
    unittest.main()
