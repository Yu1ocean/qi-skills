import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "run_daily_pipeline.py"
SPEC = importlib.util.spec_from_file_location("run_daily_pipeline", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.path.insert(0, str(REPO_ROOT))
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class _FakeCheckpoint:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def load(self):
        return dict(self.payload)

    def save(self, *args, **kwargs):
        return {"ok": True}

    def heartbeat(self, *args, **kwargs):
        return {"ok": True}

    def mark_failed(self, *args, **kwargs):
        return {"ok": True}

    def mark_completed(self, *args, **kwargs):
        return {"ok": True}


class _FakeSigtermGuard:
    def __init__(self, *_args, **_kwargs):
        self.installed = False

    def install(self):
        self.installed = True

    def uninstall(self):
        self.installed = False


class TestRunDailyPipeline(unittest.TestCase):
    def test_pipeline_runs_patrol_and_log_persist_on_non_notify_weekday(self):
        commands = []
        zombie_calls = []

        def fake_run(cmd, *, cwd=None):
            commands.append((list(cmd), cwd))
            return 0

        def fake_zombie(**kwargs):
            zombie_calls.append(kwargs)
            return {"ok": True, "detected_count": 1, "findings": []}

        argv = [
            "run_daily_pipeline.py",
            "--task-spreadsheet",
            "https://bytedance.larkoffice.com/sheets/task_demo",
            "--log-spreadsheet",
            "https://bytedance.larkoffice.com/sheets/log_demo",
            "--dry-run",
        ]

        fake_datetime = mock.Mock()
        fake_datetime.now.return_value = MODULE.datetime.datetime(2026, 6, 8, 8, 0, 0, tzinfo=MODULE.timezone.utc)
        fake_datetime.today.return_value = MODULE.datetime.datetime(2026, 6, 8, 8, 0, 0)

        with mock.patch.object(MODULE, "_run", side_effect=fake_run):
            with mock.patch.object(MODULE, "_run_zombie_sweeper", side_effect=fake_zombie):
                with mock.patch.object(MODULE, "_run_travel_dashboard_refresh", return_value={"enabled": True, "sheet_append_row_count": 0, "steps": []}):
                    with mock.patch.object(MODULE, "_maybe_push_travel_dashboard_card", return_value={"enabled": False, "status": "skipped", "reason": "not_saturday"}):
                        with mock.patch.object(MODULE, "CheckpointStore", return_value=_FakeCheckpoint()):
                            with mock.patch.object(MODULE, "SigtermGuard", return_value=_FakeSigtermGuard()):
                                with mock.patch.object(MODULE.datetime, "datetime", fake_datetime):
                                    with mock.patch.object(sys, "argv", argv):
                                        exit_code = MODULE.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(zombie_calls), 1)

        sync_index = next(
            index
            for index, (cmd, _) in enumerate(commands)
            if len(cmd) >= 2 and cmd[1] == "scripts/sync_registry_from_feishu.py"
        )
        self.assertEqual(sync_index, 1)

        invoked_scripts = [cmd[1] for cmd, _ in commands if len(cmd) >= 2 and cmd[0] == sys.executable]
        self.assertIn("scripts/run_task_patrol_save.py", invoked_scripts)
        self.assertNotIn("scripts/task_patrol_notify.py", invoked_scripts)
        self.assertIn("scripts/upload_notify_logs_to_sheet.py", invoked_scripts)
        self.assertEqual(zombie_calls[0]["checkpoint_root"].name, "checkpoints")
    def test_duplicate_active_checkpoint_exits_before_running_pipeline(self):
        commands = []
        fake_checkpoint = _FakeCheckpoint({"status": "running", "pid": 424242, "step": "task_patrol_notify"})
        argv = [
            "run_daily_pipeline.py",
            "--task-spreadsheet",
            "https://bytedance.larkoffice.com/sheets/task_demo",
            "--log-spreadsheet",
            "https://bytedance.larkoffice.com/sheets/log_demo",
        ]

        def fake_run(cmd, *, cwd=None):
            commands.append((list(cmd), cwd))
            return 0

        with mock.patch.object(MODULE, "_run", side_effect=fake_run):
            with mock.patch.object(MODULE, "CheckpointStore", return_value=fake_checkpoint):
                with mock.patch.object(MODULE, "SigtermGuard", return_value=_FakeSigtermGuard()):
                    with mock.patch.object(MODULE, "_safe_pid_exists", return_value=True):
                        with mock.patch.object(sys, "argv", argv):
                            exit_code = MODULE.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
