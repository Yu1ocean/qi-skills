#!/usr/bin/env python3
"""双轨写入（Dual-Track Write）。

把 heartbeat-inspector 的增量事件（JSON）同时写入：
- 【Aime日志】：全量审计（原始群消息快照 + 提取 JSON + 批次号）
- 【任务库】：仅写入 type=chat_task 的“任务行”

重要约束（与 feishu-doc-writing-guide 对齐）：
- 写入前必须优先通过 bytedcli-auth 进行用户身份鉴权（避免 Bot 身份 403 视野不一致）
- 实际读写通过 inner_skills/lark-sheets 的 CLI 完成（避免脚本内直连 OpenAPI）

本模块既可被 `scripts/run_inspector.py` 内部 import 调用，也提供 CLI 入口供单独运行。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

TASKFLOW_SKILL_ROOT = Path(__file__).resolve().parents[2] / "task-flow-engine"
if str(TASKFLOW_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(TASKFLOW_SKILL_ROOT))

from task_flow_engine.taskflow_ack_renderer import build_taskflow_ack_record, render_taskflow_ack_text


# 兼容两种运行方式：
# 1) 作为包导入：from scripts.dual_write import DualTrackWriter
# 2) 直接执行：python3 scripts/dual_write.py ...
try:
    from scripts.lark_sheets_cli import LarkSheetsCLI, LarkSheetsError, SheetInfo, _col_num_to_a1
except Exception:  # pragma: no cover
    from lark_sheets_cli import LarkSheetsCLI, LarkSheetsError, SheetInfo, _col_num_to_a1


def _workspace_root() -> Path:
    env = os.environ.get("IRIS_WORKSPACE_PATH")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def _run_cmd(cmd: List[str], timeout: int = 60) -> str:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed (code={p.returncode}): {' '.join(cmd)}\n{p.stdout}")
    return p.stdout


def bytedcli_auth(*, strict: bool = True) -> bool:
    """执行 bytedcli-auth。

    - strict=True：鉴权失败直接抛错（适用于写入链路）
    - strict=False：失败返回 False（适用于 best-effort 场景）
    """

    root = _workspace_root()
    script = root / "inner_skills" / "bytedcli-auth" / "scripts" / "bytedcli_auth.sh"
    if not script.exists():
        if strict:
            raise RuntimeError(f"bytedcli-auth script not found: {script}")
        return False

    try:
        _run_cmd(["bash", str(script)], timeout=60)
        return True
    except Exception:
        if strict:
            raise
        return False


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _try_parse_due_time_to_excel_serial(value: Any) -> Any:
    """把 due_time（通常为 'YYYY-MM-DD HH:MM'）尽量转换为 Excel serial number。

    目的：
    - 避免把日期时间写成“文本”（截图里 DDL 单元格左上角绿色三角）
    - 保持飞书表格对日期列的排序/筛选/条件格式能力

    返回：
    - 成功：float（Excel serial，含小数表示时间）
    - 失败：回退为原值（字符串/数字），由上层继续写入
    """

    if value is None:
        return ""

    # 已经是数字（Excel serial）
    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return ""

        # 纯数字文本
        if s.replace(".", "", 1).isdigit():
            try:
                return float(s)
            except Exception:
                return value

        # 常见日期时间格式
        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y.%m.%d",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                base = datetime(1899, 12, 30)
                delta = dt - base
                return delta.days + (delta.seconds + delta.microseconds / 1e6) / 86400.0
            except ValueError:
                continue

    # 兜底：不强行转换
    return value


def _compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _safe_get(d: Dict[str, Any], path: Sequence[str]) -> Optional[Any]:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _extract_message_snapshot(event: Dict[str, Any]) -> str:
    """尽量从事件中取“最像原始群消息”的字段。"""

    # 1) chat_task 结构里有 source_text_full
    v = _safe_get(event, ["task", "source_text_full"])
    if v:
        return str(v)

    # 2) heartbeat-inspector 的 message_new 通常有 text
    if event.get("text"):
        return str(event.get("text"))

    # 3) 兜底：整行 JSON
    return _compact_json(event)


def _collect_chat_task_contract_violations(event: Dict[str, Any]) -> List[str]:
    """对写入【任务库】前的 chat_task 做最小契约校验。

    目标不是判断任务值不值得做，而是阻止明显的非标抽取结果直接污染底表：
    - task_name 缺失或未保留 TaskFlow 约定的【】锚点
    - extractor 已明确给出 suggestion_reply，说明关键信息仍需人工确认
    - source_text_full 缺失，无法回溯原始群消息快照
    """
    if not isinstance(event, dict) or event.get("type") != "chat_task":
        return []

    task = event.get("task") or {}
    violations: List[str] = []

    task_name = str(task.get("task_name") or "").strip()
    if not task_name or not (task_name.startswith("【") and task_name.endswith("】")):
        violations.append("task_name_missing_or_not_bracketed")

    suggestion_reply = task.get("suggestion_reply")
    if isinstance(suggestion_reply, str) and suggestion_reply.strip():
        violations.append("suggestion_reply_present")

    source_text_full = task.get("source_text_full")
    if not isinstance(source_text_full, str) or not source_text_full.strip():
        violations.append("source_text_full_missing")

    return violations


def _normalize_person(value: Any) -> str:
    """把 @人/富文本/普通字符串归一成人类可读的名字。"""

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        # 常见：@人 mention block
        for k in ("name", "text", "en_name", "zh_name"):
            v = value.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            if k == "text" and s.startswith("@"):  # e.g. "@张三"
                s = s[1:].strip()
            return s
        return _compact_json(value)

    return str(value).strip()


def _normalize_person_list(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, list):
        parts = [_normalize_person(x) for x in values]
        parts = [p for p in parts if p]
        return "、".join(parts)
    return _normalize_person(values)


def _find_updated_range(resp: Dict[str, Any]) -> Optional[str]:
    """Best-effort: 从 append 返回中尝试解析“本次更新的 A1 range”。

    注意：lark-sheets-cli 不同版本的返回 schema 可能不同，因此这里做多路径兼容。
    """

    candidates: List[List[str]] = [
        ["data", "updates", "updatedRange"],
        ["data", "updates", "updated_range"],
        ["data", "updates", "updatedData", "range"],
        ["data", "updates", "updated_data", "range"],
        ["data", "updatedRange"],
        ["data", "updated_range"],
        ["data", "range"],
        ["data", "tableRange"],
    ]

    def pick(obj: Any, path: List[str]) -> Optional[str]:
        cur = obj
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
        return None

    for p in candidates:
        r = pick(resp, p)
        if r:
            return r
    return None


def _normalize_person_key(name: str) -> str:
    """用于在“姓名 → 负责人 mention 模板”里做 key 归一化。

    目标：尽量容忍输入里出现的空格、括号备注等。
    """

    s = (name or "").strip()
    # 去掉括号及括号内容：()（）[]【】
    s = re.sub(r"[\(\（\[【].*?[\)\）\]】]", "", s)
    # 去掉 @ 前缀
    s = s.lstrip("@").strip()
    # 去掉所有空白
    s = re.sub(r"\s+", "", s)
    return s


def _canonicalize_cell(value: Any) -> Any:
    """把飞书表格的 cell value 做“可比较”的规范化。

    说明：
    - 直接用 str(dict) 做 RAW 校验会因为 key 顺序/字段增补而误判。
    - 对 mention block，我们只锁定最关键的三个字段（type/token/text/name），避免平台自动补字段导致比较失败。

    注意：这里用于 RAW 校验的“比较视图”，不改变实际写入的数据。
    """

    if value is None:
        return ""

    if isinstance(value, str):
        return value

    # mention block（@人）
    if isinstance(value, dict) and value.get("type") == "mention":
        return {
            "type": "mention",
            "token": str(value.get("token") or ""),
            "text": str(value.get("text") or ""),
            "name": str(value.get("name") or ""),
        }

    # 自动链接后的富文本列表：规整为纯文本，避免 RAW 校验把“字符串 → 富文本自动转码”误判为脏写。
    if isinstance(value, list):
        if value and all(isinstance(v, dict) and str(v.get("type") or "") in {"text", "url"} for v in value):
            return "".join(str(v.get("text") or v.get("link") or "") for v in value)
        return [_canonicalize_cell(v) for v in value]

    # 其他 dict：保持结构，但保证可稳定序列化
    if isinstance(value, dict):
        # sort_keys 只在 dumps 时生效；这里先原样返回
        return value

    return value


def _canonicalize_matrix(values: List[List[Any]]) -> List[List[Any]]:
    out: List[List[Any]] = []
    for row in values:
        rr: List[Any] = []
        for c in row:
            rr.append(_canonicalize_cell(c))
        out.append(rr)
    return out


def _parse_json_from_stdout(text: str) -> Any:
    """兼容脚本 stdout 中混有日志的情况。"""

    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty stdout")

    try:
        return json.loads(text)
    except Exception:
        pass

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in reversed(lines[-20:]):
        try:
            return json.loads(ln)
        except Exception:
            pass

    blocks = re.findall(r"(\[[\s\S]*?\]|\{[\s\S]*?\})", text)
    for block in reversed(blocks):
        try:
            if len(block) > 2:
                return json.loads(block)
        except Exception:
            continue

    raise RuntimeError(f"stdout is not valid json:\n{text[-2000:]}")


@dataclass(frozen=True)
class OwnerIdentity:
    raw: str
    display_name: str
    alias_name: Optional[str] = None
    open_id: Optional[str] = None
    email: Optional[str] = None
    source: str = "sheet_roster"


def _normalize_roster_cell(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ("email", "open_id", "openId", "name", "text", "display_name", "displayName"):
            v = value.get(key)
            if v is not None:
                s = str(v).strip()
                if s:
                    return s
        return None
    if isinstance(value, list):
        for item in value:
            s = _normalize_roster_cell(item)
            if s:
                return s
        return None
    s = str(value).strip()
    return s or None


def _values_to_rows(values: List[List[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []

    header = values[0]
    header_keys: List[Optional[str]] = []
    for h in header:
        if h is None:
            header_keys.append(None)
        else:
            s = str(h).strip()
            header_keys.append(s or None)

    rows: List[Dict[str, Any]] = []
    for row_number, row in enumerate(values[1:], start=2):
        item: Dict[str, Any] = {"__row_number": row_number}
        for index, key in enumerate(header_keys):
            if not key:
                continue
            item[key] = row[index] if index < len(row) else None
        rows.append(item)
    return rows


def build_owner_directory_from_roster_rows(
    roster_rows: Sequence[Dict[str, Any]],
    *,
    name_keys: Sequence[str] = ("中文名称", "姓名", "名称"),
    open_id_keys: Sequence[str] = ("Open ID", "open_id", "openId", "OpenID"),
    email_keys: Sequence[str] = ("邮箱", "email", "Email", "邮箱地址"),
) -> Tuple[Dict[str, OwnerIdentity], List[Dict[str, Any]]]:
    def pick_first(row: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
        for key in keys:
            if key in row:
                value = _normalize_roster_cell(row.get(key))
                if value:
                    return value
        return None

    out: Dict[str, OwnerIdentity] = {}
    dup: Dict[str, List[int]] = {}

    for row in roster_rows:
        raw_name = pick_first(row, name_keys)
        if not raw_name:
            continue

        normalized_name = _normalize_person_key(raw_name)
        if not normalized_name:
            continue

        if normalized_name in out:
            dup.setdefault(normalized_name, []).append(int(row.get("__row_number") or -1))

        out[normalized_name] = OwnerIdentity(
            raw=raw_name,
            display_name=raw_name,
            open_id=pick_first(row, open_id_keys),
            email=pick_first(row, email_keys),
            source="sheet_roster",
        )

    duplicates = [
        {"normalized_name": key, "row_numbers": row_numbers}
        for key, row_numbers in sorted(dup.items(), key=lambda item: item[0])
    ]
    return out, duplicates


@dataclass
class DualWriteResult:
    batch_id: str
    written_log_rows: int
    written_task_rows: int
    raw_verified: bool
    raw_verify_skipped_reason: Optional[str] = None
    invalid_task_events: List[Dict[str, Any]] = field(default_factory=list)
    taskflow_ack_records: List[Dict[str, Any]] = field(default_factory=list)


class DualTrackWriter:
    """把 heartbeat-inspector 输出的 JSON 事件做“双轨写入”。

    轨道 A：全量审计日志写入【Aime日志】（含原始快照 + 提取 JSON + 批次号）
    轨道 B：仅 task 类事件写入【任务库】

    约束：
    - 不假设表头结构：运行时读 header 并做列对齐
    - 写入以 append 为主（避免误改动既有行）
    """

    def __init__(
        self,
        *,
        spreadsheet_token: str,
        log_sheet_title: str = "Aime日志",
        task_sheet_title: str = "任务库",
        roster_sheet_title: str = "团队名单",
        cli: Optional[LarkSheetsCLI] = None,
    ):
        self.spreadsheet_token = spreadsheet_token
        self.log_sheet_title = log_sheet_title
        self.task_sheet_title = task_sheet_title
        self.roster_sheet_title = roster_sheet_title
        self.cli = cli or LarkSheetsCLI()

        self.log_sheet: SheetInfo = self.cli.get_sheet_id(spreadsheet_token, log_sheet_title)
        self.task_sheet: SheetInfo = self.cli.get_sheet_id(spreadsheet_token, task_sheet_title)
        self.roster_sheet: Optional[SheetInfo] = None
        try:
            self.roster_sheet = self.cli.get_sheet_id(spreadsheet_token, roster_sheet_title)
        except Exception:
            self.roster_sheet = None

    def _build_owner_mention_templates(
        self,
        *,
        task_header: List[Optional[str]],
        scan_rows: int = 200,
    ) -> Dict[str, Dict[str, Any]]:
        """从【任务库】现有数据中“挖”出负责人 mention 模板。

        背景：
        - 飞书表格里“@人”是富文本对象（dict / list[dict]），不是纯字符串。
        - 仅靠 open_id/email 无法直接构造 mention token（截图里 mention.token 是一串数字）。
        - 但我们可以从表格里已经存在的 @人 单元格中提取模板，再复用其 token。

        返回：
        - {normalized_name -> mention_dict}
        """

        # 1) 找到“负责人”列
        idx: Dict[str, int] = {}
        for i, h in enumerate(task_header):
            if h:
                idx[str(h)] = i

        if "负责人" not in idx:
            return {}

        col_num_1_based = idx["负责人"] + 1
        col_a1 = _col_num_to_a1(col_num_1_based)

        # 2) 扫描范围：从第 2 行开始（跳过表头），默认扫 200 行
        end_row = max(2, min(int(self.task_sheet.row_count or 0) or scan_rows, scan_rows))
        a1_range = f"{self.task_sheet.sheet_id}!{col_a1}2:{col_a1}{end_row}"

        try:
            values = self.cli.read_range(self.spreadsheet_token, a1_range)
        except Exception:
            # 读失败不影响写入主流程：回退为纯文本负责人
            return {}

        out: Dict[str, Dict[str, Any]] = {}

        def add(v: Any) -> None:
            if not v:
                return
            if isinstance(v, dict) and v.get("type") == "mention":
                name = str(v.get("name") or "").strip()
                if not name:
                    return
                out[_normalize_person_key(name)] = v
                return
            if isinstance(v, list):
                for x in v:
                    add(x)

        for r in values:
            if not r:
                continue
            add(r[0])

        return out

    def _build_owner_directory(self) -> tuple[List[Optional[str]], Dict[str, OwnerIdentity]]:
        if not self.roster_sheet:
            return [], {}

        roster_header = self.cli.read_header(self.spreadsheet_token, self.roster_sheet)
        roster_values = self.cli.read_range(self.spreadsheet_token, self.roster_sheet.sheet_id)
        roster_rows = _values_to_rows(roster_values)
        owner_directory, _duplicates = build_owner_directory_from_roster_rows(roster_rows)
        return roster_header, owner_directory

    def _build_plain_owner_text_from_identity(self, identity: OwnerIdentity) -> Optional[str]:
        display_name = str(identity.display_name or identity.raw or "").strip()
        return display_name or None

    def _build_mention_from_owner_identity(self, identity: OwnerIdentity) -> Optional[Dict[str, Any]]:
        display_name = self._build_plain_owner_text_from_identity(identity)
        if not display_name:
            return None
        if identity.open_id:
            return {
                "type": "mention",
                "text": identity.open_id,
                "textType": "openId",
                "notify": False,
                "name": display_name,
            }
        if identity.email:
            return {
                "type": "mention",
                "text": identity.email,
                "textType": "email",
                "notify": False,
                "name": display_name,
            }
        return None

    def _extract_event_chat_ids(self, event: Dict[str, Any]) -> List[str]:
        out: List[str] = []

        def add(value: Any) -> None:
            if isinstance(value, str) and value.startswith("oc_") and value not in out:
                out.append(value)

        add(event.get("chat_id"))

        task = event.get("task") or {}
        source_messages_full = task.get("source_messages_full") or []
        if isinstance(source_messages_full, list):
            for item in source_messages_full:
                if isinstance(item, dict):
                    add(item.get("chat_id"))

        return out

    def _extract_lark_users_from_response(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if not isinstance(payload, dict):
            return []

        candidates = [
            payload.get("users"),
            payload.get("members"),
            payload.get("items"),
            payload.get("data"),
            (payload.get("data") or {}).get("users") if isinstance(payload.get("data"), dict) else None,
            (payload.get("data") or {}).get("members") if isinstance(payload.get("data"), dict) else None,
            (payload.get("data") or {}).get("items") if isinstance(payload.get("data"), dict) else None,
        ]

        for items in candidates:
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]

        return []

    def _lookup_owner_identity_via_chat_members(self, owner_name: str, *, chat_id: str) -> Optional[OwnerIdentity]:
        root = _workspace_root()
        script = root / "inner_skills" / "lark" / "mcp_lark_lark_user_info.py"
        if not script.exists():
            return None

        out = _run_cmd(["python3", str(script), json.dumps({"chat_id": chat_id}, ensure_ascii=False)], timeout=60)
        data = _parse_json_from_stdout(out)
        users = self._extract_lark_users_from_response(data)
        if not users:
            return None

        normalized_target = _normalize_person_key(owner_name)
        if not normalized_target:
            return None

        hits: List[OwnerIdentity] = []
        for user in users:
            name_candidates = [
                user.get("name"),
                user.get("display_name"),
                user.get("displayName"),
                user.get("zh_name"),
                user.get("zhName"),
                user.get("user_name"),
                user.get("nickname"),
            ]
            matched_name: Optional[str] = None
            for candidate in name_candidates:
                candidate_text = _normalize_roster_cell(candidate)
                if not candidate_text:
                    continue
                if _normalize_person_key(candidate_text) == normalized_target:
                    matched_name = candidate_text
                    break
            if not matched_name:
                continue

            alias_name = _normalize_roster_cell(
                user.get("name")
                or user.get("en_name")
                or user.get("enName")
                or user.get("display_name")
                or user.get("displayName")
                or user.get("zh_name")
                or user.get("zhName")
            )
            open_id = _normalize_roster_cell(user.get("open_id") or user.get("openId"))
            email = _normalize_roster_cell(
                user.get("email")
                or user.get("enterprise_email")
                or user.get("enterpriseEmail")
                or user.get("contact_email")
            )
            if not open_id and not email:
                continue

            hits.append(
                OwnerIdentity(
                    raw=owner_name,
                    display_name=matched_name,
                    alias_name=alias_name or matched_name,
                    open_id=open_id,
                    email=email,
                    source=f"chat_member:{chat_id}",
                )
            )

        if len(hits) == 1:
            return hits[0]
        return None

    def _append_owner_to_roster(
        self,
        identity: OwnerIdentity,
        *,
        roster_header: List[Optional[str]],
        raw_verify: bool,
    ) -> None:
        if not self.roster_sheet or not roster_header:
            return

        kv: Dict[str, Any] = {}

        for key in ("中文名称", "姓名", "名称"):
            if key in roster_header:
                kv[key] = identity.display_name
                break
        for key in ("英文名/花名", "英文名", "花名", "英文花名", "English Name", "Alias"):
            if key in roster_header:
                kv[key] = identity.alias_name or identity.display_name
                break
        for key in ("邮箱", "email", "Email", "邮箱地址"):
            if key in roster_header and identity.email:
                kv[key] = identity.email
                break
        for key in ("Open ID", "open_id", "openId", "OpenID"):
            if key in roster_header and identity.open_id:
                kv[key] = identity.open_id
                break

        row = self.cli.make_row_by_header(roster_header, kv)
        if not any(cell not in (None, "") for cell in row):
            return

        append_range = f"{self.roster_sheet.sheet_id}!A1:{_col_num_to_a1(max(1, len(roster_header)))}1"
        self._append_and_verify(
            spreadsheet_token=self.spreadsheet_token,
            append_range=append_range,
            chunk=[row],
            enable_raw_verify=raw_verify,
        )

    def _resolve_owner_identity(
        self,
        owner_name: str,
        *,
        owner_directory: Dict[str, OwnerIdentity],
        event: Dict[str, Any],
        roster_header: List[Optional[str]],
        raw_verify: bool,
    ) -> Optional[OwnerIdentity]:
        key = _normalize_person_key(owner_name)
        if not key:
            return None

        cached = owner_directory.get(key)
        if cached and (cached.email or cached.open_id):
            return cached

        for chat_id in self._extract_event_chat_ids(event):
            try:
                identity = self._lookup_owner_identity_via_chat_members(owner_name, chat_id=chat_id)
            except Exception:
                identity = None
            if not identity:
                continue

            owner_directory[key] = identity
            try:
                self._append_owner_to_roster(identity, roster_header=roster_header, raw_verify=raw_verify)
            except Exception:
                pass
            return identity

        return cached

    def _owners_to_sheet_cell(
        self,
        owner_names: List[str],
        *,
        mention_templates: Dict[str, Dict[str, Any]],
        owner_directory: Dict[str, OwnerIdentity],
        event: Dict[str, Any],
        roster_header: List[Optional[str]],
        raw_verify: bool,
    ) -> tuple[Any, bool]:
        """把负责人名单转成可写入飞书表格的 cell value。

        返回：
        - cell value
        - 是否使用了基于 email/open_id 组装的 mention（这类写法 RAW 校验可能不稳定）
        """

        names = [n.strip() for n in owner_names if isinstance(n, str) and n.strip()]
        if not names:
            return "", False

        cell_items: List[Any] = []
        used_programmatic_mention = False
        for n in names:
            key = _normalize_person_key(n)
            tmpl = mention_templates.get(key)

            if not tmpl:
                prefix = key[:2] if len(key) >= 2 else key
                if prefix:
                    cands = [v for k, v in mention_templates.items() if k.startswith(prefix) or prefix.startswith(k)]
                    if len(cands) == 1:
                        tmpl = cands[0]

            if tmpl:
                cell_items.append(tmpl)
                continue

            identity = self._resolve_owner_identity(
                n,
                owner_directory=owner_directory,
                event=event,
                roster_header=roster_header,
                raw_verify=raw_verify,
            )
            mention = self._build_mention_from_owner_identity(identity) if identity else None
            if mention:
                cell_items.append(mention)
                used_programmatic_mention = True
                continue

            owner_text = self._build_plain_owner_text_from_identity(identity) if identity else None
            cell_items.append(owner_text or n)

        if len(cell_items) == 1:
            return cell_items[0], used_programmatic_mention
        if all(isinstance(item, str) for item in cell_items):
            return "、".join(str(item).strip() for item in cell_items if str(item).strip()), used_programmatic_mention
        return cell_items, used_programmatic_mention

    def _build_log_kv(self, event: Dict[str, Any], batch_id: str, write_time: str) -> Dict[str, Any]:
        event_type = event.get("type")
        owners = _safe_get(event, ["task", "owners"])
        owners_text = _normalize_person_list(owners)

        task_name = _safe_get(event, ["task", "task_name"]) or ""
        due_time = (
            _safe_get(event, ["task", "due_time"])
            or _safe_get(event, ["status_update", "postponed_to_time"])
            or ""
        )

        return {
            # 兼容当前表头（A~F）
            "交付结果": task_name or (event_type or ""),
            "完成情况": "",
            "分类": event_type or "",
            "负责人": owners_text,
            "DDL": due_time,
            "进展": _extract_message_snapshot(event),
            # 新增审计字段（G~K）
            "写入时间": write_time,
            "消息来源": f"heartbeat-inspector:{event_type}",
            "原始群消息快照": _extract_message_snapshot(event),
            "大模型提取 JSON": _compact_json(event),
            "批次号": batch_id,
        }

    def _build_task_kv(
        self,
        event: Dict[str, Any],
        *,
        mention_templates: Dict[str, Dict[str, Any]],
        owner_directory: Dict[str, OwnerIdentity],
        roster_header: List[Optional[str]],
        raw_verify: bool,
        default_status: str = "进行中",
        default_category: str = "",
    ) -> tuple[Optional[Dict[str, Any]], bool]:
        if event.get("type") != "chat_task":
            return None, False

        task = event.get("task") or {}

        task_name = (task.get("task_name") or "").strip()
        if not task_name:
            # 不允许静默写空任务名：用醒目占位显影
            task_name = "⚠️[MISSING: task_name]"

        # owners: 可能是 list / dict(mention block) / str
        owners_raw = task.get("owners")
        owner_names: List[str] = []
        if isinstance(owners_raw, list):
            for x in owners_raw:
                n = _normalize_person(x)
                if n:
                    owner_names.append(n)
        else:
            s = _normalize_person(owners_raw)
            if s:
                # 兼容“张三、李四/王五”这种字符串
                parts = re.split(r"[、，,/;；]+", s)
                owner_names.extend([p.strip() for p in parts if p.strip()])

        owners_cell, used_programmatic_mention = self._owners_to_sheet_cell(
            owner_names,
            mention_templates=mention_templates,
            owner_directory=owner_directory,
            event=event,
            roster_header=roster_header,
            raw_verify=raw_verify,
        )

        due_time_raw = task.get("due_time") or task.get("ddl") or ""
        due_time_cell = _try_parse_due_time_to_excel_serial(due_time_raw)

        # Ack-Lock / 状态提示：不要塞进“完成情况”下拉里（会导致标签不渲染）
        ack_tag = _safe_get(task, ["ack_lock", "tag"]) or task.get("status") or ""
        ack_tag = str(ack_tag).strip()

        progress = (task.get("source_text_full") or event.get("text") or "").strip()
        if ack_tag:
            progress = (f"{ack_tag} {progress}").strip()

        # 分类：默认留空，避免写入一个不在下拉选项里的文本导致“标签样式失效”
        category = (default_category or "").strip()

        status = (default_status or "").strip() or "进行中"

        return {
            "交付结果": task_name,
            "完成情况": status,
            "分类": category,
            "负责人": owners_cell,
            "DDL": due_time_cell,
            "进展": progress,
        }, used_programmatic_mention

    def _append_and_verify(
        self,
        *,
        spreadsheet_token: str,
        append_range: str,
        chunk: List[List[Any]],
        enable_raw_verify: bool,
    ) -> tuple[bool, Optional[str]]:
        resp = self.cli.append_rows(spreadsheet_token, append_range, chunk)

        if not enable_raw_verify:
            return False, "raw_verify_disabled"

        updated_range = _find_updated_range(resp)
        if not updated_range:
            return False, "append_response_missing_updated_range"

        # RAW 原子锁：写→等→读
        time.sleep(2)
        values = self.cli.read_range(spreadsheet_token, updated_range)

        got = _canonicalize_matrix(values)
        want = _canonicalize_matrix(chunk)
        if len(got) < len(want):
            raise LarkSheetsError(
                "RAW 校验失败：读回行数小于写入行数\n"
                f"updated_range={updated_range}\n"
                f"want_rows={len(want)} got_rows={len(got)}\n"
                f"resp={json.dumps(resp, ensure_ascii=False)[:2000]}"
            )

        tail = got[-len(want) :]
        if tail != want:
            raise LarkSheetsError(
                "RAW 校验失败：读回内容与写入内容不一致\n"
                f"updated_range={updated_range}\n"
                f"want_tail={json.dumps(want, ensure_ascii=False, sort_keys=True)[:2000]}\n"
                f"got_tail={json.dumps(tail, ensure_ascii=False, sort_keys=True)[:2000]}\n"
                f"resp={json.dumps(resp, ensure_ascii=False)[:2000]}"
            )

        return True, None

    def write_events(
        self,
        events: Iterable[Dict[str, Any]],
        *,
        batch_id: Optional[str] = None,
        write_time: Optional[str] = None,
        chunk_size: int = 50,
        dry_run: bool = False,
        raw_verify: bool = True,
    ) -> DualWriteResult:
        batch_id = batch_id or f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        write_time = write_time or _now_iso()

        # 读表头并缓存
        log_header = self.cli.read_header(self.spreadsheet_token, self.log_sheet)
        task_header = self.cli.read_header(self.spreadsheet_token, self.task_sheet)
        roster_header, owner_directory = self._build_owner_directory()

        # 从任务库中挖出“负责人 @人”的 mention 模板（用于后续写入保持样式）
        owner_mention_templates = self._build_owner_mention_templates(task_header=task_header)

        # +append 的 range 必须覆盖 values 的列宽；否则会报 90202 (columns of value > range)
        log_col_count = max(1, len(log_header))
        task_col_count = max(1, len(task_header))
        log_append_range = f"{self.log_sheet.sheet_id}"
        task_append_range = f"{self.task_sheet.sheet_id}"

        log_rows: List[List[Any]] = []
        task_rows: List[List[Any]] = []
        task_row_programmatic_mentions: List[bool] = []
        invalid_task_events: List[Dict[str, Any]] = []
        taskflow_ack_records: List[Dict[str, Any]] = []

        for ev in events:
            if not isinstance(ev, dict):
                continue

            log_kv = self._build_log_kv(ev, batch_id=batch_id, write_time=write_time)
            log_rows.append(self.cli.make_row_by_header(log_header, log_kv))

            contract_violations = _collect_chat_task_contract_violations(ev)
            if contract_violations:
                invalid_task_events.append(
                    {
                        "type": ev.get("type") or "",
                        "task_name": _safe_get(ev, ["task", "task_name"]) or "",
                        "violations": contract_violations,
                        "source_text_full": _safe_get(ev, ["task", "source_text_full"]) or "",
                    }
                )
                continue

            task_kv, used_programmatic_mention = self._build_task_kv(
                ev,
                mention_templates=owner_mention_templates,
                owner_directory=owner_directory,
                roster_header=roster_header,
                raw_verify=raw_verify,
            )
            if task_kv:
                task_rows.append(self.cli.make_row_by_header(task_header, task_kv))
                task_row_programmatic_mentions.append(used_programmatic_mention)
                task = ev.get("task") or {}
                owner_text = _normalize_person_list(task.get("owners")) or _normalize_person(task.get("owner")) or "待补充"
                status_text = str(task.get("status") or _safe_get(task, ["ack_lock", "tag"]) or "✅ 已入库").strip() or "✅ 已入库"
                taskflow_ack_records.append(
                    build_taskflow_ack_record(
                        task_name=task.get("task_name") or "",
                        owner=owner_text,
                        status=status_text,
                    )
                )

        if dry_run:
            return DualWriteResult(
                batch_id=batch_id,
                written_log_rows=len(log_rows),
                written_task_rows=len(task_rows),
                raw_verified=False,
                raw_verify_skipped_reason="dry_run",
                invalid_task_events=invalid_task_events,
                taskflow_ack_records=taskflow_ack_records,
            )

        written_log = 0
        written_task = 0
        verified_any = False
        skipped_reason: Optional[str] = None

        # 分块追加，避免单次过大
        for i in range(0, len(log_rows), chunk_size):
            chunk = log_rows[i : i + chunk_size]
            if not chunk:
                continue
            ok, reason = self._append_and_verify(
                spreadsheet_token=self.spreadsheet_token,
                append_range=log_append_range,
                chunk=chunk,
                enable_raw_verify=raw_verify,
            )
            verified_any = verified_any or ok
            skipped_reason = skipped_reason or reason
            written_log += len(chunk)

        for i in range(0, len(task_rows), chunk_size):
            chunk = task_rows[i : i + chunk_size]
            if not chunk:
                continue
            chunk_uses_programmatic_mentions = any(task_row_programmatic_mentions[i : i + chunk_size])
            enable_task_raw_verify = raw_verify and not chunk_uses_programmatic_mentions
            ok, reason = self._append_and_verify(
                spreadsheet_token=self.spreadsheet_token,
                append_range=task_append_range,
                chunk=chunk,
                enable_raw_verify=enable_task_raw_verify,
            )
            verified_any = verified_any or ok
            if chunk_uses_programmatic_mentions:
                skipped_reason = skipped_reason or "task_rows_contain_programmatic_mentions"
            else:
                skipped_reason = skipped_reason or reason
            written_task += len(chunk)

        return DualWriteResult(
            batch_id=batch_id,
            written_log_rows=written_log,
            written_task_rows=written_task,
            raw_verified=verified_any,
            raw_verify_skipped_reason=None if verified_any else skipped_reason,
            invalid_task_events=invalid_task_events,
            taskflow_ack_records=taskflow_ack_records,
        )


def _iter_events_from_jsonl(path: str) -> Iterable[Dict[str, Any]]:
    if path == "-":
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
        return

    p = Path(path)
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--spreadsheet",
        required=True,
        help="电子表格 URL 或 token（支持 wiki URL / sheets URL / spreadsheet_token）",
    )
    ap.add_argument("--log-sheet-title", default="Aime日志")
    ap.add_argument("--task-sheet-title", default="任务库")
    ap.add_argument(
        "--roster-sheet-title",
        default="团队名单",
        help="花名册所在工作表标题（默认：团队名单）",
    )
    ap.add_argument(
        "--input-jsonl",
        required=True,
        help="heartbeat-inspector 输出的 JSONL 文件路径；用 - 表示 stdin",
    )
    ap.add_argument("--batch-id", default=None, help="可选：指定批次号（不传则自动生成）")
    ap.add_argument("--dry-run", action="store_true", help="只计算将写入多少行，不实际写表")
    ap.add_argument(
        "--no-raw-verify",
        action="store_true",
        help="禁用 RAW 写后即读校验（默认开启；仅在确认底层 CLI 无法返回 updatedRange 时使用）",
    )
    args = ap.parse_args()

    # 写入链路：默认 strict，鉴权失败直接熔断
    bytedcli_auth(strict=True)

    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(args.spreadsheet)

    writer = DualTrackWriter(
        spreadsheet_token=spreadsheet_token,
        log_sheet_title=args.log_sheet_title,
        task_sheet_title=args.task_sheet_title,
        roster_sheet_title=args.roster_sheet_title,
        cli=cli,
    )

    events = list(_iter_events_from_jsonl(args.input_jsonl))
    result = writer.write_events(
        events,
        batch_id=args.batch_id,
        dry_run=args.dry_run,
        raw_verify=not bool(args.no_raw_verify),
    )

    try:
        print(
            json.dumps(
                {
                    "ok": True,
                    "batch_id": result.batch_id,
                    "written_log_rows": result.written_log_rows,
                    "written_task_rows": result.written_task_rows,
                    "taskflow_ack_count": len(result.taskflow_ack_records),
                    "taskflow_ack_records": result.taskflow_ack_records,
                    "invalid_task_event_count": len(result.invalid_task_events),
                    "invalid_task_events": result.invalid_task_events,
                    "dry_run": bool(args.dry_run),
                    "raw_verified": result.raw_verified,
                    "raw_verify_skipped_reason": result.raw_verify_skipped_reason,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except BrokenPipeError:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
