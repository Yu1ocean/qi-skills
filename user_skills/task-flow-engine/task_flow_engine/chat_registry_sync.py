from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from task_flow_engine.chat_registry import ChatRegistryEntry, default_chat_registry_path
from task_flow_engine.lark_sheets_cli import LarkSheetsCLI, SheetInfo

DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL = "https://bytedance.larkoffice.com/sheets/FvkIslPSgh4XGqtcUqychqU7nzb"
DEFAULT_CHAT_REGISTRY_DESCRIPTION = "Chat Registry SSOT。所有 chat_id 必须从飞书主表同步到此文件，禁止从上下文、缓存或历史日志猜测。"

USAGE_HEADER = "用途标识 (Usage Key)"
CHAT_ID_HEADER = "群聊 ID (Chat ID)"
EXPECTED_KEYWORDS_HEADER = "预期群名关键字 (Expected Name Keywords)"
OWNER_HEADER = "环境/Owner (Env/Owner)"
REMARKS_HEADER = "最后更新时间/备注 (Last Updated/Remarks)"

REQUIRED_HEADERS = (
    USAGE_HEADER,
    CHAT_ID_HEADER,
    EXPECTED_KEYWORDS_HEADER,
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MULTI_VALUE_SPLIT_RE = re.compile(r"[,，|;；\n]+")


class ChatRegistrySyncError(RuntimeError):
    """Raised when syncing Chat Registry from Feishu fails."""


@dataclass(frozen=True)
class ChatRegistrySyncResult:
    spreadsheet_token: str
    sheet_title: str
    synced_usages: tuple[str, ...]
    output_path: Path
    updated_at: str
    default_usage: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "spreadsheet_token": self.spreadsheet_token,
            "sheet_title": self.sheet_title,
            "synced_usages": list(self.synced_usages),
            "synced_count": len(self.synced_usages),
            "output_path": str(self.output_path),
            "updated_at": self.updated_at,
            "default_usage": self.default_usage,
            "overwritten": True,
        }


@dataclass(frozen=True)
class _CmdResult:
    returncode: int
    stdout: str
    stderr: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_cmd(cmd: Sequence[str], *, cwd: Optional[Path] = None) -> _CmdResult:
    process = subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return _CmdResult(
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def require_bytedcli_auth() -> None:
    workspace_root = _workspace_root()
    auth_sh = workspace_root / "inner_skills" / "bytedcli-auth" / "scripts" / "bytedcli_auth.sh"
    if not auth_sh.exists():
        raise FileNotFoundError(f"找不到 bytedcli-auth：{auth_sh}")

    result = _run_cmd(["bash", str(auth_sh)], cwd=auth_sh.parent)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ChatRegistrySyncError(f"bytedcli-auth 执行失败：{detail or 'unknown error'}")


def _validate_output_path(path: Path) -> Path:
    workspace_root = _workspace_root().resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ChatRegistrySyncError(
            f"output 必须位于工作区内：{resolved} (workspace_root={workspace_root})"
        ) from exc
    return resolved


def resolve_output_path(output: Optional[str]) -> Path:
    if not output:
        return default_chat_registry_path().resolve()

    path = Path(output)
    if not path.is_absolute():
        path = _repo_root() / path
    return _validate_output_path(path)


def _choose_sheet(cli: LarkSheetsCLI, spreadsheet_token: str, sheet_title: Optional[str]) -> SheetInfo:
    sheets = cli.info(spreadsheet_token)
    if not sheets:
        raise ChatRegistrySyncError("飞书表格中没有可读取的工作表")

    if sheet_title:
        for sheet in sheets:
            if sheet.title == sheet_title:
                return sheet
        raise ChatRegistrySyncError(f"找不到工作表：{sheet_title}；现有={[sheet.title for sheet in sheets]}")

    if len(sheets) != 1:
        raise ChatRegistrySyncError(
            "表格包含多个工作表，必须显式指定 --sheet-title。"
            f"现有={[sheet.title for sheet in sheets]}"
        )
    return sheets[0]


def _values_to_rows(values: List[List[Any]]) -> List[Dict[str, Any]]:
    if not values:
        return []

    header = values[0]
    header_keys: List[Optional[str]] = []
    for cell in header:
        if cell is None:
            header_keys.append(None)
        else:
            text = str(cell).strip()
            header_keys.append(text or None)

    rows: List[Dict[str, Any]] = []
    for row_number, row in enumerate(values[1:], start=2):
        item: Dict[str, Any] = {"__row_number": row_number}
        has_any_value = False
        for index, key in enumerate(header_keys):
            if not key:
                continue
            value = row[index] if index < len(row) else None
            if value not in (None, ""):
                has_any_value = True
            item[key] = value
        if has_any_value:
            rows.append(item)
    return rows


def _ensure_required_headers(rows: List[Dict[str, Any]], values: List[List[Any]]) -> None:
    if not values:
        raise ChatRegistrySyncError("飞书表为空，无法同步 Chat Registry")

    header_row = values[0]
    normalized_headers = {str(cell).strip() for cell in header_row if str(cell or "").strip()}
    missing = [header for header in REQUIRED_HEADERS if header not in normalized_headers]
    if missing:
        raise ChatRegistrySyncError(f"飞书表缺少必需列：{missing}; headers={sorted(normalized_headers)}")

    if not rows:
        raise ChatRegistrySyncError("飞书表没有可同步的数据行")


def _flatten_cell_strings(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, dict):
        out: List[str] = []
        for key in ("text", "link", "email", "value", "name"):
            if key in value:
                out.extend(_flatten_cell_strings(value.get(key)))
        if out:
            return out
        return [json.dumps(value, ensure_ascii=False, sort_keys=True)]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            out.extend(_flatten_cell_strings(item))
        return out
    text = str(value).strip()
    return [text] if text else []


def _cell_to_text(value: Any) -> str:
    return " ".join(part for part in _flatten_cell_strings(value) if part).strip()


def _extract_first_email(value: Any) -> Optional[str]:
    for part in _flatten_cell_strings(value):
        match = _EMAIL_RE.search(part)
        if match:
            return match.group(0)
    return None


def _split_keywords(value: Any) -> List[str]:
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            parts.extend(_split_keywords(item))
        return list(dict.fromkeys(parts))

    text = _cell_to_text(value)
    if not text:
        return []

    tokens = [token.strip() for token in _MULTI_VALUE_SPLIT_RE.split(text)]
    return [token for token in dict.fromkeys(tokens) if token]


def _parse_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ChatRegistrySyncError(f"无法解析布尔值：{value}")


def _parse_updated_at(text: Optional[str]) -> Optional[str]:
    value = str(text or "").strip()
    if not value:
        return None

    normalized = value.replace("/", "-").replace(".", "-")
    try:
        if len(normalized) == 10:
            return datetime.strptime(normalized, "%Y-%m-%d").date().isoformat()
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return None


_ALIAS_MAP = {
    "name": "name",
    "群名": "name",
    "chat_name": "name",
    "lookup_query": "lookup_query",
    "查询关键字": "lookup_query",
    "搜索关键字": "lookup_query",
    "search_query": "lookup_query",
    "default_usage": "default_usage",
    "默认用途": "default_usage",
    "updated_at": "updated_at",
    "last_updated": "updated_at",
    "最后更新时间": "updated_at",
    "note": "description",
    "备注": "description",
    "说明": "description",
    "description": "description",
    "allow_group_broadcast_by_default": "allow_group_broadcast_by_default",
    "allow_broadcast": "allow_group_broadcast_by_default",
    "默认允许群播": "allow_group_broadcast_by_default",
}


def _normalize_remark_key(key: str) -> str:
    raw = str(key or "").strip()
    if not raw:
        return raw
    lowered = raw.lower()
    return _ALIAS_MAP.get(raw, _ALIAS_MAP.get(lowered, raw))


def _parse_remark_metadata(value: Any) -> Dict[str, str]:
    text = _cell_to_text(value)
    if not text:
        return {}

    result: Dict[str, str] = {}
    plain_notes: List[str] = []
    for segment in re.split(r"[;；]\s*", text):
        item = segment.strip()
        if not item:
            continue
        match = re.match(r"^(?P<key>[^=:=：]+?)\s*(?:=|:|：)\s*(?P<value>.+)$", item)
        if not match:
            plain_notes.append(item)
            continue
        key = _normalize_remark_key(match.group("key"))
        if not key:
            plain_notes.append(item)
            continue
        result[key] = match.group("value").strip()
    if plain_notes:
        existing = result.get("description")
        joined = "；".join(plain_notes)
        result["description"] = f"{existing}；{joined}" if existing else joined
    return result


def _parse_json_object_from_stdout(stdout: str) -> Dict[str, Any]:
    text = (stdout or "").strip()
    if "[RESULT]" in text:
        text = text.split("[RESULT]", 1)[1].strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ChatRegistrySyncError("飞书群元信息返回无法解析为 JSON object")


def _extract_chats(parsed: Mapping[str, Any]) -> List[Dict[str, Any]]:
    candidates = [parsed, parsed.get("data") if isinstance(parsed.get("data"), dict) else None]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        chats = candidate.get("chats")
        if isinstance(chats, list):
            return [dict(chat) for chat in chats if isinstance(chat, dict)]
        exact_match = candidate.get("exact_match")
        if isinstance(exact_match, dict):
            return [dict(exact_match)]
    return []


class FeishuChatSearchClient:
    def __init__(self) -> None:
        self.workspace_root = _workspace_root()
        self.skill_dir = self.workspace_root / "inner_skills" / "feishu-im-read"
        self.search_chats = self.skill_dir / "scripts" / "feishu_im_user_search_chats.js"
        if not self.search_chats.exists():
            raise FileNotFoundError(f"找不到飞书群聊搜索脚本：{self.search_chats}")

    def get_chat_metadata(self, chat_id: str, query: str) -> Dict[str, Any]:
        if not query:
            raise ChatRegistrySyncError(f"chat_id={chat_id} 缺少 lookup_query，无法拉取群元信息")
        cmd = [
            "node",
            "scripts/feishu_im_user_search_chats.js",
            "--input",
            json.dumps({"query": query, "page_size": 100}, ensure_ascii=False),
        ]
        result = _run_cmd(cmd, cwd=self.skill_dir)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ChatRegistrySyncError(f"pre-flight 拉取群元信息失败：{detail or 'unknown error'}")

        parsed = _parse_json_object_from_stdout(result.stdout)
        chats = _extract_chats(parsed)
        for chat in chats:
            if str(chat.get("chat_id") or "").strip() == chat_id:
                return dict(chat)
        raise ChatRegistrySyncError(
            f"pre-flight 未能通过 lookup_query={query!r} 找到 registry chat_id={chat_id}；"
            "请检查飞书主表中的预期关键字配置。"
        )


def build_registry_payload_from_rows(
    rows: List[Dict[str, Any]],
    *,
    spreadsheet_token: str,
    sheet_title: str,
    metadata_resolver: Optional[Callable[[str, str], Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    chats: Dict[str, Dict[str, Any]] = {}
    updated_at_candidates: List[str] = []
    explicit_default_usage: Optional[str] = None

    for row in rows:
        row_number = row.get("__row_number", "?")
        usage = str(row.get(USAGE_HEADER) or "").strip()
        if not usage:
            continue

        chat_id = str(row.get(CHAT_ID_HEADER) or "").strip()
        if not chat_id:
            raise ChatRegistrySyncError(f"第 {row_number} 行缺少 chat_id")

        keywords = _split_keywords(row.get(EXPECTED_KEYWORDS_HEADER))
        if not keywords:
            raise ChatRegistrySyncError(f"第 {row_number} 行缺少预期群名关键字")

        admin_email = _extract_first_email(row.get(OWNER_HEADER))
        remark_meta = _parse_remark_metadata(row.get(REMARKS_HEADER))
        explicit_lookup_query = str(remark_meta.get("lookup_query") or "").strip() or None
        description = str(remark_meta.get("description") or "").strip()
        updated_at = _parse_updated_at(remark_meta.get("updated_at"))
        if updated_at:
            updated_at_candidates.append(updated_at)

        default_usage = str(remark_meta.get("default_usage") or "").strip() or None
        if default_usage:
            if explicit_default_usage and explicit_default_usage != default_usage:
                raise ChatRegistrySyncError(
                    f"飞书表 default_usage 配置冲突：{explicit_default_usage} vs {default_usage}"
                )
            explicit_default_usage = default_usage

        provisional_query = explicit_lookup_query or keywords[0]
        actual_metadata: Optional[Mapping[str, Any]] = None
        actual_name: Optional[str] = None
        if metadata_resolver is not None:
            actual_metadata = metadata_resolver(chat_id, provisional_query)
            actual_name = str(actual_metadata.get("name") or "").strip() or None

        lookup_query = explicit_lookup_query or actual_name or provisional_query
        entry_payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "name": actual_name or str(remark_meta.get("name") or "").strip() or usage,
            "expected_name_keywords": keywords,
            "lookup_query": lookup_query,
            "description": description,
            "allow_group_broadcast_by_default": _parse_bool(
                remark_meta.get("allow_group_broadcast_by_default"),
                default=False,
            ),
        }
        if admin_email:
            entry_payload["admin_email"] = admin_email

        entry = ChatRegistryEntry.from_mapping(usage, entry_payload)
        if actual_metadata is not None:
            entry.assert_metadata(actual_metadata)
            entry_payload["name"] = str(actual_metadata.get("name") or entry.name).strip() or entry.name
            entry = ChatRegistryEntry.from_mapping(usage, entry_payload)

        chats[usage] = {
            "chat_id": entry.chat_id,
            "name": entry.name,
            "lookup_query": entry.lookup_query,
            "expected_name_keywords": list(entry.expected_name_keywords),
            "description": entry.description,
            "admin_email": entry.admin_email,
            "allow_group_broadcast_by_default": entry.allow_group_broadcast_by_default,
        }

    if not chats:
        raise ChatRegistrySyncError("飞书表中没有可同步的 Chat Registry 行")

    default_usage = explicit_default_usage or (
        "task_patrol_broadcast" if "task_patrol_broadcast" in chats else next(iter(chats.keys()))
    )
    if default_usage not in chats:
        raise ChatRegistrySyncError(f"default_usage={default_usage} 不存在于 chats 中")

    updated_at = max(updated_at_candidates) if updated_at_candidates else datetime.now(timezone.utc).date().isoformat()
    return {
        "version": 1,
        "updated_at": updated_at,
        "description": DEFAULT_CHAT_REGISTRY_DESCRIPTION,
        "default_usage": default_usage,
        "source": {
            "spreadsheet_token": spreadsheet_token,
            "sheet_title": sheet_title,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        },
        "chats": chats,
    }


def _validate_registry_payload(payload: Mapping[str, Any], output_path: Path) -> None:
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        from task_flow_engine.chat_registry import ChatRegistry

        ChatRegistry.load(temp_path)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def sync_chat_registry_from_feishu(
    *,
    spreadsheet: str = DEFAULT_CHAT_REGISTRY_SPREADSHEET_URL,
    sheet_title: Optional[str] = None,
    output_path: Optional[Path] = None,
    skip_auth: bool = False,
) -> ChatRegistrySyncResult:
    if not skip_auth:
        require_bytedcli_auth()

    cli = LarkSheetsCLI()
    spreadsheet_token = cli.resolve_spreadsheet_token(spreadsheet)
    target_output_path = _validate_output_path((output_path or default_chat_registry_path()).resolve())
    sheet = _choose_sheet(cli, spreadsheet_token, sheet_title)
    values = cli.read_range(spreadsheet_token, sheet.sheet_id)
    rows = _values_to_rows(values)
    _ensure_required_headers(rows, values)

    metadata_client = FeishuChatSearchClient()
    payload = build_registry_payload_from_rows(
        rows,
        spreadsheet_token=spreadsheet_token,
        sheet_title=sheet.title,
        metadata_resolver=metadata_client.get_chat_metadata,
    )
    _validate_registry_payload(payload, target_output_path)
    return ChatRegistrySyncResult(
        spreadsheet_token=spreadsheet_token,
        sheet_title=sheet.title,
        synced_usages=tuple(payload["chats"].keys()),
        output_path=target_output_path,
        updated_at=str(payload["updated_at"]),
        default_usage=str(payload["default_usage"]),
    )
