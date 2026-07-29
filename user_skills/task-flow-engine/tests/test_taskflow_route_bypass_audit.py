import tempfile
from pathlib import Path

from scripts.taskflow_route_bypass_audit import audit_taskflow_route_bypass


def test_audit_passes_on_clean_tree():
    with tempfile.TemporaryDirectory(prefix="taskflow_audit_clean_") as tmp:
        root = Path(tmp)
        (root / "ok.py").write_text("print('ok')\n", encoding="utf-8")
        result = audit_taskflow_route_bypass(root)

    assert result["ok"] is True
    assert result["violation_count"] == 0


def test_audit_flags_illegal_bypass_patterns():
    with tempfile.TemporaryDirectory(prefix="taskflow_audit_bad_") as tmp:
        root = Path(tmp)
        (root / "send_l1_reply.py").write_text("print('legacy')\n", encoding="utf-8")
        (root / "bad_sender.py").write_text("tool = 'lark_im_send_message'\nparams = {'reply_to': 'om_xxx'}\n", encoding="utf-8")
        result = audit_taskflow_route_bypass(root)

    assert result["ok"] is False
    assert result["violation_count"] == 3
    details = "\n".join(item["detail"] for item in result["violations"])
    assert "send_l1_reply.py" in details
    assert "lark_im_send_message" in details
    assert "reply_to" in details
