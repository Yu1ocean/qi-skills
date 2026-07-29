import tempfile
from pathlib import Path

from scripts.cross_skill_taskflow_guard_audit import audit_roots


def test_cross_skill_audit_respects_allowlist_and_passes_clean_targets():
    with tempfile.TemporaryDirectory(prefix="cross_skill_audit_ok_") as tmp:
        base = Path(tmp)
        target = base / "user_skills" / "centralized-transmitter" / "scripts"
        target.mkdir(parents=True, exist_ok=True)
        (target / "centralized_transmitter.py").write_text("tool = 'lark_im_send_message'\n", encoding="utf-8")
        result = audit_roots([target.parent.parent], base_dir=base)

    assert result["ok"] is True
    assert result["violation_count"] == 0


def test_cross_skill_audit_flags_bypass_in_other_targets():
    with tempfile.TemporaryDirectory(prefix="cross_skill_audit_bad_") as tmp:
        base = Path(tmp)
        taskflow_root = base / "user_skills" / "task-flow-engine" / "scripts"
        taskflow_root.mkdir(parents=True, exist_ok=True)
        (taskflow_root / "send_l1_reply.py").write_text("print('legacy')\n", encoding="utf-8")
        (taskflow_root / "bad_sender.py").write_text("tool = 'lark_im_send_message'\nparams = {'reply_to': 'om_xxx'}\n", encoding="utf-8")
        result = audit_roots([taskflow_root.parent], base_dir=base)

    assert result["ok"] is False
    assert result["violation_count"] == 3
    details = "\n".join(item["detail"] for item in result["violations"])
    assert "send_l1_reply.py" in details
    assert "lark_im_send_message" in details
    assert "reply_to" in details
