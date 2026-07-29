import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "utils" / "anti_restart.py"
SPEC = importlib.util.spec_from_file_location("anti_restart", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class TestAntiRestart(unittest.TestCase):
    def setUp(self):
        tmp_root = REPO_ROOT / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="anti_restart_test_", dir=str(tmp_root)))

    def tearDown(self):
        for path in sorted(self.temp_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        if self.temp_dir.exists():
            self.temp_dir.rmdir()

    def test_checkpoint_store_persists_and_updates_status(self):
        checkpoint_path = self.temp_dir / "demo.json"
        store = MODULE.CheckpointStore(checkpoint_path, task_name="demo", task_id="demo-1")
        store.save(status="running", step="download", progress={"pct": 10}, payload={"foo": "bar"})
        store.mark_completed(step="done", progress={"pct": 100}, payload={"foo": "baz"})

        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["step"], "done")
        self.assertEqual(payload["progress"]["pct"], 100)
        self.assertEqual(payload["payload"]["foo"], "baz")
        self.assertEqual(payload["task_name"], "demo")
        self.assertEqual(payload["task_id"], "demo-1")

    def test_sigterm_guard_flushes_last_checkpoint(self):
        checkpoint_path = self.temp_dir / "guard.json"
        store = MODULE.CheckpointStore(checkpoint_path, task_name="guard-demo", task_id="guard-demo")
        guard = MODULE.SigtermGuard(
            store,
            snapshot_provider=lambda: {"current_step": "transcribe", "chunk": 7},
            exit_code=None,
        )

        guard._handle(int(MODULE.signal.SIGTERM), None)

        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "terminating")
        self.assertEqual(payload["step"], "transcribe")
        self.assertEqual(payload["signal"], "SIGTERM")
        self.assertEqual(payload["payload"]["chunk"], 7)
        self.assertIn("被系统强杀", payload["note"])

    def test_zombie_sweeper_marks_stale_dead_pid(self):
        checkpoint_root = self.temp_dir / "runtime"
        checkpoint_root.mkdir(parents=True, exist_ok=True)
        stale_path = checkpoint_root / "long_task.json"
        stale_payload = {
            "task_name": "Long Task",
            "task_id": "long-task-1",
            "status": "running",
            "pid": 999999,
            "heartbeat_at": "2026-05-20T00:00:00+00:00",
            "updated_at": "2026-05-20T00:00:00+00:00",
        }
        stale_path.write_text(json.dumps(stale_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with mock.patch.object(MODULE, "_utcnow", return_value=MODULE.datetime.fromisoformat("2026-05-22T12:00:00+00:00")):
            findings = MODULE.ZombieSweeper(checkpoint_root, stale_after_seconds=3600).scan()

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].task_id, "long-task-1")
        updated = json.loads(stale_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["status"], "zombie")
        self.assertFalse(updated["last_known_pid_alive"])
        self.assertIn("断链_待自愈", updated["zombie_reason"])

    def test_inject_zombie_alerts_merges_into_admin_and_summary(self):
        alerts = {
            "summary": {"today": "2026-05-22", "total_findings": 2, "counts": {"已超期": 2}},
            "grouped_results": {"已超期": [{"key": "1"}, {"key": "2"}]},
            "routes": {"admin": {"count": 0, "items": [], "message": ""}},
        }
        findings = [
            MODULE.ZombieFinding(
                task_id="task-1",
                task_name="Long Task",
                checkpoint_path="/tmp/task-1.json",
                pid=1234,
                status_before="running",
                last_heartbeat_at="2026-05-22T00:00:00+00:00",
                stale_seconds=7200,
                reason="Heartbeat 超时",
            )
        ]

        merged = MODULE.inject_zombie_alerts(
            alerts,
            findings,
            checkpoint_root=Path("/tmp/checkpoints"),
            stale_after_seconds=3600,
        )

        self.assertEqual(merged["summary"]["total_findings"], 3)
        self.assertEqual(merged["summary"]["counts"]["僵尸任务"], 1)
        self.assertEqual(len(merged["grouped_results"]["僵尸任务"]), 1)
        self.assertEqual(merged["routes"]["admin"]["count"], 1)
        self.assertIn("僵尸任务扫盲告警", merged["routes"]["admin"]["message"])


if __name__ == "__main__":
    unittest.main()
