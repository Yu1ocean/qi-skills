"""测试 patrol.extract_pending_users 的缺席成员识别逻辑。"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from patrol import extract_pending_users  # noqa: E402


CST = timezone(timedelta(hours=8))


def _write_fixture_xlsx(path: Path) -> None:
    top3_df = pd.DataFrame(
        [
            {
                "周日期": "Week 22\n5/24-5/30",
                "序号": 1,
                "标签": "策略",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@于奇楠",
            },
            {
                "周日期": "Week 22\n5/24-5/30",
                "序号": 2,
                "标签": "协同",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@于奇楠",
            },
            {
                "周日期": "Week 22\n5/24-5/30",
                "序号": 3,
                "标签": "商家",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@于奇楠",
            },
        ]
    )
    roster_df = pd.DataFrame(
        [
            {"中文名称": "于奇楠", "邮箱": "yuqinan@bytedance.com", "Open ID": "ou_yuqinan"},
            {"中文名称": "李京达", "邮箱": "lijingda.666@bytedance.com", "Open ID": "ou_lijingda"},
            {"中文名称": "焦彦晨", "邮箱": "jiaoyanchen@bytedance.com", "Open ID": "ou_jiaoyanchen"},
        ]
    )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        top3_df.to_excel(writer, sheet_name="重要三件事", index=False)
        roster_df.to_excel(writer, sheet_name="团队名单", index=False)



def test_absent_owner_should_be_pending_but_exempt_owner_should_not():
    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_path = Path(tmpdir) / "fixture.xlsx"
        _write_fixture_xlsx(xlsx_path)

        pending, meta = extract_pending_users(
            xlsx_path,
            datetime(2026, 5, 25, 20, 0, tzinfo=CST),
        )

    pending_emails = {item["email"] for item in pending}
    assert "lijingda.666@bytedance.com" in pending_emails
    assert "jiaoyanchen@bytedance.com" not in pending_emails

    status_by_owner = {item["owner"]: item["status"] for item in meta["owner_blocks"]}
    assert status_by_owner["李京达"] == "pending_absent_from_sheet"
    assert status_by_owner["焦彦晨"] == "exempt_filtered_absent"



def test_date_token_fallback_matches_current_week_rows():
    top3_df = pd.DataFrame(
        [
            {
                "周日期": "7月6号-10号",
                "序号": 1,
                "标签": "商家",
                "计划": "",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            },
            {
                "周日期": "7月6号-10号",
                "序号": 2,
                "标签": "商家",
                "计划": "",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            },
            {
                "周日期": "7月6号-10号",
                "序号": 3,
                "标签": "商家",
                "计划": "",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            },
        ]
    )
    roster_df = pd.DataFrame(
        [
            {"中文名称": "张志强", "邮箱": "zhangzhiqiang@example.com", "Open ID": "ou_zhang"},
            {"中文名称": "测试用户B", "邮箱": "testuser_b@example.com", "Open ID": "ou_testb"},
        ]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_path = Path(tmpdir) / "fixture_fallback.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            top3_df.to_excel(writer, sheet_name="重要三件事", index=False)
            roster_df.to_excel(writer, sheet_name="团队名单", index=False)

        pending, meta = extract_pending_users(
            xlsx_path,
            datetime(2026, 7, 6, 16, 0, tzinfo=CST),
        )

    assert len(pending) >= 1
    pending_names = {u["name"] for u in pending}
    assert "张志强" in pending_names
    assert meta["week_marker"].endswith("(fallback_by_date_token)")



def test_owner_self_should_be_in_monitoring_roster_when_absent():
    top3_df = pd.DataFrame(
        [
            {
                "周日期": "Week 28\n7/6-7/12",
                "序号": 1,
                "标签": "商家",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            },
            {
                "周日期": "Week 28\n7/6-7/12",
                "序号": 2,
                "标签": "商家",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            },
            {
                "周日期": "Week 28\n7/6-7/12",
                "序号": 3,
                "标签": "商家",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            },
        ]
    )
    roster_df = pd.DataFrame(
        [
            {"中文名称": "于奇楠", "邮箱": "yuqinan@bytedance.com", "Open ID": "ou_yuqinan"},
            {"中文名称": "张志强", "邮箱": "zhangzhiqiang@example.com", "Open ID": "ou_zhang"},
        ]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_path = Path(tmpdir) / "fixture_owner.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            top3_df.to_excel(writer, sheet_name="重要三件事", index=False)
            roster_df.to_excel(writer, sheet_name="团队名单", index=False)

        pending, meta = extract_pending_users(
            xlsx_path,
            datetime(2026, 7, 6, 16, 0, tzinfo=CST),
        )

    pending_names = {item["name"] for item in pending}
    assert "于奇楠" in pending_names
    status_by_owner = {item["owner"]: item["status"] for item in meta["owner_blocks"]}
    assert status_by_owner["于奇楠"] == "pending_absent_from_sheet"


def test_empty_roster_should_raise_roster_empty_error() -> None:
    """roster 人数低于阈值（ROSTER_MIN_COUNT=2）时，必须抛出 RosterEmptyError，禁止静默输出 pending_users: []。"""
    import os
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from patrol import RosterEmptyError  # noqa: E402

    top3_df = pd.DataFrame(
        [
            {
                "周日期": "Week 28\n7/7-7/13",
                "序号": 1,
                "标签": "策略",
                "计划": "已填写",
                "完成进度": "",
                "Remark": "",
                "负责人": "@张志强",
            }
        ]
    )
    # roster 只有 1 人，低于默认阈值 2
    roster_df = pd.DataFrame(
        [
            {"中文名称": "张志强", "邮箱": "zhangzhiqiang@example.com", "Open ID": "ou_zhang"},
        ]
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_path = Path(tmpdir) / "fixture_empty_roster.xlsx"
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            top3_df.to_excel(writer, sheet_name="重要三件事", index=False)
            roster_df.to_excel(writer, sheet_name="团队名单", index=False)

        env_backup = os.environ.get("WEEKLY_TOP3_ROSTER_MIN_COUNT")
        os.environ["WEEKLY_TOP3_ROSTER_MIN_COUNT"] = "2"
        try:
            import importlib
            import patrol as patrol_mod
            importlib.reload(patrol_mod)
            from patrol import extract_pending_users as _extract  # noqa: E402
            try:
                _extract(xlsx_path, datetime(2026, 7, 8, 16, 0, tzinfo=CST))
                raise AssertionError("期望抛出 RosterEmptyError，但未抛出")
            except RosterEmptyError as exc:
                assert exc.status == "ERROR_ROSTER_EMPTY"
                assert exc.raw_evidence["roster_count"] == 1
        finally:
            if env_backup is None:
                os.environ.pop("WEEKLY_TOP3_ROSTER_MIN_COUNT", None)
            else:
                os.environ["WEEKLY_TOP3_ROSTER_MIN_COUNT"] = env_backup


if __name__ == "__main__":
    test_absent_owner_should_be_pending_but_exempt_owner_should_not()
    test_date_token_fallback_matches_current_week_rows()
    test_owner_self_should_be_in_monitoring_roster_when_absent()
    test_empty_roster_should_raise_roster_empty_error()
    print("4/4 passed")
