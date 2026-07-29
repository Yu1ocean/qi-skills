import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from task_flow_engine.chat_registry import default_broadcast_chat_id


# -----------------------------
# 基础：单元格归一化 / DDL 解析
# -----------------------------

def _normalize_text(value: Any) -> Optional[str]:
    """把单元格值归一成可比较/可展示的文本。

    说明：飞书表格读取时，@人等富文本可能以 dict 结构返回。
    """

    if value is None:
        return None

    if isinstance(value, str):
        s = value.strip()
        return s or None

    if isinstance(value, dict):
        # 常见：@人 mention block
        for k in ("zh_name", "name", "text", "en_name"):
            v = value.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if not s:
                continue
            if k == "text" and s.startswith("@"):  # e.g. "@张三"
                s = s[1:].strip()
            return s or None

        # 兜底：保留原结构，避免静默丢信息
        return json.dumps(value, ensure_ascii=False)

    if isinstance(value, (list, tuple)):
        parts: List[str] = []
        for x in value:
            sx = _normalize_text(x)
            if sx:
                parts.append(sx)
        return "、".join(parts) or None

    s = str(value).strip()
    return s or None


def _normalize_person_key(name: str) -> str:
    """用于“中文姓名 → 飞书成员”映射的 key 归一化。

    目标：尽量容忍输入里出现的空格、括号备注等。

    示例：
    - "夏春雨" -> "夏春雨"
    - "夏春雨（代理）" -> "夏春雨"
    - " 夏春雨 " -> "夏春雨"
    """

    s = (name or "").strip()
    # 去掉括号及括号内容：()（）[]【】
    s = re.sub(r"[\(\（\[【].*?[\)\）\]】]", "", s)
    # 去掉 @ 前缀
    s = s.lstrip("@").strip()
    # 去掉所有空白
    s = re.sub(r"\s+", "", s)
    return s


def split_people(text: Optional[str]) -> List[str]:
    """把“负责人”字段拆成多人列表。

    支持常见分隔符：
    - 顿号/逗号：、，,
    - 斜杠：/
    - 分号：;；
    """

    s = (text or "").strip()
    if not s:
        return []

    parts = re.split(r"[、，,/;；]+", s)
    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        out.append(p)
    return out


def parse_ddl(ddl_text: Any, today: date) -> Tuple[Optional[date], Optional[str]]:
    """解析 DDL。

    返回：
    - (parsed_date, None) 成功
    - (None, reason) 失败，其中 reason 用于细分：缺失 vs 格式异常
    """

    ddl_text = _normalize_text(ddl_text)
    if not ddl_text:
        return None, "empty"

    # 处理 Excel/飞书表格的数字序列日期 (e.g. 46152)
    if isinstance(ddl_text, str) and ddl_text.replace(".", "", 1).isdigit():
        try:
            days = float(ddl_text)
            # Excel 1900 日期系统基准为 1899-12-30
            return date(1899, 12, 30) + timedelta(days=int(days)), None
        except (ValueError, OverflowError):
            pass

    # 允许带时间：2026-05-02 19:00 / 2026-05-02 19:00:00
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
            return datetime.strptime(ddl_text, fmt).date(), None
        except ValueError:
            pass

    m = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", ddl_text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        try:
            return date(today.year, month, day), None
        except ValueError:
            return None, "invalid_month_day"

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", ddl_text)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        try:
            return date(today.year, month, day), None
        except ValueError:
            return None, "invalid_month_day"

    return None, "unrecognized"


def is_done(status_text: Any) -> bool:
    s = _normalize_text(status_text)
    if not s:
        return False
    # 兼容“已完成 / 完成 / done / ✅”
    return s in {"已完成", "完成", "done", "Done", "DONE", "✅"} or "已完成" in s or "/done" in s


def is_started(status_text: Any) -> bool:
    s = _normalize_text(status_text)
    if not s:
        return False
    return s in {"进行中", "开启", "Started", "doing"} or "进行中" in s


def is_paused(status_text: Any) -> bool:
    s = _normalize_text(status_text)
    if not s:
        return False
    return s in {"暂停", "挂起", "Paused", "paused", "stopped"} or "暂停" in s


# -----------------------------
# 核心数据结构
# -----------------------------


@dataclass(frozen=True)
class OwnerIdentity:
    """负责人身份（用于后续私聊 / @）。

    - raw：表格中出现的原始文本（拆分后单个 owner）
    - display_name：用于展示（优先中文名）
    - open_id/email：用于后续 IM 精准投递或 @ 提及
    """

    raw: str
    display_name: str
    open_id: Optional[str] = None
    email: Optional[str] = None
    source: str = "sheet"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "display_name": self.display_name,
            "open_id": self.open_id,
            "email": self.email,
            "source": self.source,
        }


def _normalize_roster_cell(value: Any) -> Optional[str]:
    """把花名册单元格归一成字符串。

    花名册一般是纯文本，但也可能出现：
    - 邮箱列被识别为对象
    - Open ID 列被写成富文本

    这里尽量复用 `_normalize_text` 的行为。
    """

    return _normalize_text(value)


def build_owner_directory_from_roster_rows(
    roster_rows: Sequence[Dict[str, Any]],
    *,
    name_keys: Sequence[str] = ("中文名称",),
    open_id_keys: Sequence[str] = ("Open ID", "open_id", "openId", "OpenID"),
    email_keys: Sequence[str] = ("邮箱", "email", "Email", "邮箱地址"),
) -> Tuple[Dict[str, OwnerIdentity], List[Dict[str, Any]]]:
    """从【团队名单】Sheet 的行字典构建负责人映射。

    约定：
    - 用 `中文名称` 列来匹配【任务库】里的“负责人”（匹配时会做 `_normalize_person_key` 归一化）。
    - 当负责人字段被误填成邮箱占位符时，也允许通过邮箱反查回中文名。
    - 产出 `OwnerIdentity.open_id` 与 `OwnerIdentity.email`，供后续告警路由使用（私聊优先 email）。

    返回：
    - owner_directory: {normalized_alias -> OwnerIdentity}
    - duplicates: 重名/重复 key 的行信息（仅做提示，不影响主流程）
    """

    def pick_first(row: Dict[str, Any], keys: Sequence[str]) -> Optional[str]:
        for k in keys:
            if k in row:
                v = _normalize_roster_cell(row.get(k))
                if v:
                    return v
        return None

    out: Dict[str, OwnerIdentity] = {}
    dup: Dict[str, List[int]] = {}

    def register_alias(alias: Optional[str], identity: OwnerIdentity) -> None:
        normalized = _normalize_person_key(alias or "")
        if not normalized:
            return
        out[normalized] = identity

    for r in roster_rows:
        raw_name = pick_first(r, name_keys)
        if not raw_name:
            continue

        key = _normalize_person_key(raw_name)
        if not key:
            continue

        open_id = pick_first(r, open_id_keys)
        email = pick_first(r, email_keys)

        if key in out:
            dup.setdefault(key, []).append(int(r.get("__row_number") or -1))

        identity = OwnerIdentity(
            raw=raw_name,
            display_name=raw_name,
            open_id=open_id,
            email=email,
            source="sheet_roster",
        )
        register_alias(raw_name, identity)
        register_alias(email, identity)

    duplicates = [
        {"normalized_name": k, "row_numbers": v}
        for k, v in sorted(dup.items(), key=lambda x: x[0])
    ]
    return out, duplicates


@dataclass
class PatrolFinding:
    """一次巡检中识别出的“异常/风险项”。"""

    key: str
    row: int
    task: str
    status: Optional[str]
    owners: List[OwnerIdentity]
    ddl_raw: Any
    ddl_parsed: Optional[str]
    delta_days: Optional[int]
    alert_category: str
    reason: str
    issue_type: str  # due_soon | overdue | missing_ddl | format_error
    overdue_days: Optional[int] = None
    abnormal_days: Optional[int] = None  # 连续发现缺失/格式异常天数（需要 state 才能算）
    stage: Optional[str] = None  # private | group

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "row": self.row,
            "task": self.task,
            "status": self.status,
            "owners": [o.to_dict() for o in self.owners],
            "ddl_raw": self.ddl_raw,
            "ddl_parsed": self.ddl_parsed,
            "delta_days": self.delta_days,
            "alert_category": self.alert_category,
            "reason": self.reason,
            "issue_type": self.issue_type,
            "overdue_days": self.overdue_days,
            "abnormal_days": self.abnormal_days,
            "stage": self.stage,
        }


# -----------------------------
# 状态持久化：连续异常天数
# -----------------------------


@dataclass
class _TaskState:
    last_seen: str  # YYYY-MM-DD
    issue_type: str
    consecutive_days: int


class PatrolStateStore:
    """本地状态缓存，用于“连续异常天数 / 防抖”。"""

    def __init__(self, path: Path):
        self.path = path
        self.version = 1
        self._tasks: Dict[str, _TaskState] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._tasks = {}
            return

        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # 读失败时不抛硬错误：避免一次坏文件让巡检全挂
            self._tasks = {}
            return

        tasks = obj.get("tasks") or {}
        out: Dict[str, _TaskState] = {}
        for k, v in tasks.items():
            if not isinstance(v, dict):
                continue
            last_seen = str(v.get("last_seen") or "")
            issue_type = str(v.get("issue_type") or "")
            consecutive_days = int(v.get("consecutive_days") or 0)
            if not last_seen or not issue_type or consecutive_days <= 0:
                continue
            out[k] = _TaskState(last_seen=last_seen, issue_type=issue_type, consecutive_days=consecutive_days)
        self._tasks = out

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        obj = {
            "version": self.version,
            "updated_at": date.today().isoformat(),
            "tasks": {
                k: {
                    "last_seen": v.last_seen,
                    "issue_type": v.issue_type,
                    "consecutive_days": v.consecutive_days,
                }
                for k, v in sorted(self._tasks.items())
            },
        }

        # 原子写：先写临时文件，再 replace
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def bump(self, task_key: str, issue_type: str, today: date) -> int:
        """更新并返回当前连续天数。

        规则：
        - 同一天多次跑：保持不变（不重复+1）
        - 间隔 1 天：+1
        - 其他情况：重置为 1
        """

        prev = self._tasks.get(task_key)
        if prev is None:
            self._tasks[task_key] = _TaskState(last_seen=today.isoformat(), issue_type=issue_type, consecutive_days=1)
            return 1

        if prev.issue_type != issue_type:
            self._tasks[task_key] = _TaskState(last_seen=today.isoformat(), issue_type=issue_type, consecutive_days=1)
            return 1

        try:
            last = date.fromisoformat(prev.last_seen)
        except ValueError:
            self._tasks[task_key] = _TaskState(last_seen=today.isoformat(), issue_type=issue_type, consecutive_days=1)
            return 1

        if last == today:
            return prev.consecutive_days

        if last + timedelta(days=1) == today:
            new_days = prev.consecutive_days + 1
        else:
            new_days = 1

        self._tasks[task_key] = _TaskState(last_seen=today.isoformat(), issue_type=issue_type, consecutive_days=new_days)
        return new_days

    def clear(self, task_key: str) -> None:
        self._tasks.pop(task_key, None)


# -----------------------------
# 群聊卡片瘦身：广播群锁定 / 去重聚合 / 增量展示
# -----------------------------

BROADCAST_CHAT_ID = default_broadcast_chat_id()
DEFAULT_COMPACT_CARD_MAX_ITEMS_PER_GROUP = 3
COMPACT_CARD_CATEGORY_ORDER: List[Tuple[str, str]] = [
    ("已超期", "🔴"),
    ("缺失 DDL", "🟡"),
    ("格式异常", "🟣"),
]
COMPACT_CARD_CATEGORY_ICONS = {name: icon for name, icon in COMPACT_CARD_CATEGORY_ORDER}


def default_broadcast_target_chat() -> Dict[str, Any]:
    return {"chat_id": BROADCAST_CHAT_ID, "name": ""}


class PatrolCardSnapshotStore:
    """本地卡片快照缓存，用于“仅展示相对昨日新增/变化异常”。"""

    def __init__(self, path: Path):
        self.path = path
        self.version = 1
        self._snapshot: Dict[str, str] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._snapshot = {}
            return

        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._snapshot = {}
            return

        snapshot = obj.get("snapshot") or {}
        if not isinstance(snapshot, dict):
            self._snapshot = {}
            return
        self._snapshot = {str(k): str(v) for k, v in snapshot.items()}

    def snapshot(self) -> Dict[str, str]:
        return dict(self._snapshot)

    def save(self, snapshot: Dict[str, str], *, today: date) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        obj = {
            "version": self.version,
            "updated_at": today.isoformat(),
            "snapshot": dict(sorted((str(k), str(v)) for k, v in (snapshot or {}).items())),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        self._snapshot = obj["snapshot"]


@dataclass(frozen=True)
class CompactCardEntry:
    category: str
    title_key: str
    title: str
    raw_count: int
    sample: PatrolFinding
    owners: Tuple[OwnerIdentity, ...]

    @property
    def snapshot_key(self) -> str:
        return f"{self.category}:{self.title_key}"

    @property
    def snapshot_signature(self) -> str:
        payload = {
            "title": self.title,
            "raw_count": self.raw_count,
            "issue_type": self.sample.issue_type,
            "reason": self.sample.reason,
            "ddl_parsed": self.sample.ddl_parsed,
            "ddl_raw": _normalize_text(self.sample.ddl_raw),
            "delta_days": self.sample.delta_days,
            "overdue_days": self.sample.overdue_days,
            "abnormal_days": self.sample.abnormal_days,
            "owners": [o.email or o.open_id or o.display_name for o in self.owners],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _card_task_title_key(task: str) -> str:
    return re.sub(r"\s+", " ", (task or "").strip()).lower()


def _card_owner_route_key(owner: OwnerIdentity) -> str:
    return owner.email or owner.open_id or owner.display_name


def _card_entry_sort_key(item: PatrolFinding) -> Tuple[int, int, int, str]:
    row = item.row if item.row is not None else 10**9
    task = item.task or ""
    if item.alert_category == "已超期":
        return (0, -(item.overdue_days or 0), row, task)
    if item.alert_category == "缺失 DDL":
        return (1, -(item.abnormal_days or 0), row, task)
    if item.alert_category == "格式异常":
        return (2, -(item.abnormal_days or 0), row, task)
    if item.alert_category == "临近到期":
        return (3, item.delta_days if item.delta_days is not None else 10**9, row, task)
    return (9, 0, row, task)


def _merge_card_owners(items: Sequence[PatrolFinding]) -> Tuple[OwnerIdentity, ...]:
    seen: set[str] = set()
    owners: List[OwnerIdentity] = []
    for item in items:
        for owner in item.owners:
            route_key = _card_owner_route_key(owner)
            if not route_key or route_key in seen:
                continue
            seen.add(route_key)
            owners.append(owner)
    return tuple(owners)


def _build_compact_card_groups(items: Sequence[PatrolFinding]) -> "OrderedDict[str, List[CompactCardEntry]]":
    grouped_items: "OrderedDict[str, List[PatrolFinding]]" = OrderedDict(
        (name, []) for name, _ in COMPACT_CARD_CATEGORY_ORDER
    )
    for item in sorted(items, key=_card_entry_sort_key):
        grouped_items.setdefault(item.alert_category, []).append(item)

    compact_groups: "OrderedDict[str, List[CompactCardEntry]]" = OrderedDict()
    for category in list(grouped_items.keys()):
        dedup: "OrderedDict[str, List[PatrolFinding]]" = OrderedDict()
        for item in grouped_items.get(category, []):
            dedup.setdefault(_card_task_title_key(item.task), []).append(item)

        compact_groups[category] = [
            CompactCardEntry(
                category=category,
                title_key=title_key,
                title=bucket[0].task,
                raw_count=len(bucket),
                sample=bucket[0],
                owners=_merge_card_owners(bucket),
            )
            for title_key, bucket in dedup.items()
        ]
    return compact_groups


def _build_compact_card_snapshot(items: Sequence[PatrolFinding]) -> Dict[str, str]:
    snapshot: Dict[str, str] = {}
    for entries in _build_compact_card_groups(items).values():
        for entry in entries:
            snapshot[entry.snapshot_key] = entry.snapshot_signature
    return snapshot


def _render_compact_owner_label(owner: Optional[OwnerIdentity]) -> str:
    if owner is None:
        return "**未分配**"
    return _at_in_card(owner.open_id, owner.display_name)


def _render_compact_task_label(entry: CompactCardEntry) -> str:
    label = f"`{entry.title}`"
    if entry.raw_count > 1:
        label += f" x{entry.raw_count}"
    return label


def _build_compact_owner_buckets(entries: Sequence[CompactCardEntry]) -> List[Dict[str, Any]]:
    category_names = [name for name, _ in COMPACT_CARD_CATEGORY_ORDER]
    buckets: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for entry in sorted(entries, key=lambda item: _card_entry_sort_key(item.sample)):
        owners: Sequence[Optional[OwnerIdentity]] = entry.owners or (None,)
        for owner in owners:
            owner_key = _card_owner_route_key(owner) if owner is not None else "__unassigned__"
            bucket = buckets.setdefault(
                owner_key,
                {
                    "owner": owner,
                    "display_name": owner.display_name if owner is not None else "未分配",
                    "total_raw_count": 0,
                    "categories": OrderedDict((name, []) for name in category_names),
                },
            )
            bucket["categories"].setdefault(entry.category, []).append(entry)
            bucket["total_raw_count"] += entry.raw_count

    return sorted(
        buckets.values(),
        key=lambda bucket: (-int(bucket["total_raw_count"]), str(bucket["display_name"])),
    )


def _render_compact_category_line(category: str, entries: Sequence[CompactCardEntry], *, max_tasks_per_category: int) -> str:
    raw_count = sum(entry.raw_count for entry in entries)
    shown_entries = list(entries[:max_tasks_per_category])
    shown_raw_count = sum(entry.raw_count for entry in shown_entries)
    task_labels = [_render_compact_task_label(entry) for entry in shown_entries]
    hidden_raw_count = max(raw_count - shown_raw_count, 0)
    if hidden_raw_count > 0:
        task_labels.append(f"等 {hidden_raw_count} 项")

    icon = COMPACT_CARD_CATEGORY_ICONS.get(category, "⚪️")
    return f"- {icon} **{category}**：{raw_count} 项（{'、'.join(task_labels)}）"


def _render_compact_owner_section(bucket: Dict[str, Any], *, max_tasks_per_category: int) -> Tuple[str, Dict[str, Any]]:
    owner = bucket.get("owner")
    total_raw_count = int(bucket.get("total_raw_count") or 0)
    category_map: Dict[str, List[CompactCardEntry]] = dict(bucket.get("categories") or {})

    lines = [f"👤 {_render_compact_owner_label(owner)}：共 {total_raw_count} 项异常"]
    category_summaries: List[Dict[str, Any]] = []
    extra_categories = [name for name in category_map.keys() if name not in COMPACT_CARD_CATEGORY_ICONS]
    for category in [name for name, _ in COMPACT_CARD_CATEGORY_ORDER] + extra_categories:
        entries = category_map.get(category, [])
        if not entries:
            continue
        lines.append(_render_compact_category_line(category, entries, max_tasks_per_category=max_tasks_per_category))
        category_summaries.append(
            {
                "category": category,
                "raw_count": sum(entry.raw_count for entry in entries),
                "shown_titles": [entry.title for entry in list(entries)[:max_tasks_per_category]],
            }
        )

    return "\n".join(lines), {
        "owner": bucket.get("display_name"),
        "raw_count": total_raw_count,
        "categories": category_summaries,
    }


def _render_compact_patrol_card_body(
    items: Sequence[PatrolFinding],
    *,
    today: date,
    summary_label: str,
    max_items_per_group: int,
    only_changed: bool,
    previous_snapshot: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    previous_snapshot = previous_snapshot or {}
    compact_groups = _build_compact_card_groups(items)
    current_snapshot: Dict[str, str] = {}

    filtered_entries: List[CompactCardEntry] = []
    extra_categories = [name for name in compact_groups.keys() if name not in COMPACT_CARD_CATEGORY_ICONS]
    for category in [name for name, _ in COMPACT_CARD_CATEGORY_ORDER] + extra_categories:
        entries = compact_groups.get(category, [])
        for entry in entries:
            current_snapshot[entry.snapshot_key] = entry.snapshot_signature
        if only_changed:
            entries = [entry for entry in entries if previous_snapshot.get(entry.snapshot_key) != entry.snapshot_signature]
        filtered_entries.extend(entries)

    visible_total = sum(entry.raw_count for entry in filtered_entries)
    sections: List[str] = [
        "\n".join(
            [
                f"**日期**：{today.isoformat()}",
                f"**{summary_label}**：{visible_total}（全量 {len(items)}）" if only_changed else f"**{summary_label}**：{len(items)}",
                (
                    f"**展示策略**：先按负责人聚合，再按异常类别归类；每位负责人在每个类别下最多展开 {max_items_per_group} 项任务，"
                    "同名去重，仅展示较昨日新增/变化异常"
                )
                if only_changed
                else (
                    f"**展示策略**：先按负责人聚合，再按异常类别归类；每位负责人在每个类别下最多展开 {max_items_per_group} 项任务，同名去重"
                ),
            ]
        )
    ]

    owner_buckets = _build_compact_owner_buckets(filtered_entries)
    owner_summaries: List[Dict[str, Any]] = []
    for bucket in owner_buckets:
        section_md, section_meta = _render_compact_owner_section(bucket, max_tasks_per_category=max_items_per_group)
        sections.append(section_md)
        owner_summaries.append(section_meta)

    if only_changed and not owner_buckets:
        sections.append("✅ 今日相对昨日无新增/变化异常，完整列表见工作站。")

    meta = {
        "summary_label": summary_label,
        "max_items_per_group": max_items_per_group,
        "only_changed": only_changed,
        "snapshot": current_snapshot,
        "visible_total": visible_total if only_changed else len(items),
        "total_items": len(items),
        "rendered_owners": owner_summaries,
    }
    return "\n\n".join(section for section in sections if section).strip(), meta


def build_compact_patrol_card_a(
    *,
    items: Sequence[PatrolFinding],
    today: date,
    title: str,
    template: str,
    summary_label: str,
    action_text: str,
    action_url: str,
    max_items_per_group: int = DEFAULT_COMPACT_CARD_MAX_ITEMS_PER_GROUP,
    only_changed: bool = False,
    previous_snapshot: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if not items:
        return None, {
            "summary_label": summary_label,
            "max_items_per_group": max_items_per_group,
            "only_changed": only_changed,
            "snapshot": {},
            "visible_total": 0,
            "total_items": 0,
            "rendered_groups": [],
        }

    body_md, meta = _render_compact_patrol_card_body(
        items,
        today=today,
        summary_label=summary_label,
        max_items_per_group=max_items_per_group,
        only_changed=only_changed,
        previous_snapshot=previous_snapshot,
    )
    return (
        build_patrol_card_a(
            title=title,
            template=template,
            body_md=body_md,
            action_text=action_text,
            action_url=action_url,
        ),
        meta,
    )


# -----------------------------
# 卡片模板（schema 2.0）
# -----------------------------


def _at_in_card(open_id: Optional[str], display_name: str) -> str:
    """卡片 markdown 的 @ 语法。

    说明：飞书卡片 markdown 对 @ 的语法在不同环境可能略有差异。
    这里输出一个通用占位：
    - 有 open_id：使用 `<at id=...></at>`
    - 无 open_id：回退为 `@姓名`

    上层如需更严格的控制，可直接使用 finding.owners[*].open_id 来构建 post/card。
    """

    if open_id:
        return f"<at id=\"{open_id}\"></at>"
    return f"@{display_name}"


def build_patrol_card(*, title: str, template: str, summary_md: str, detail_md: str) -> Dict[str, Any]:
    """旧版卡片渲染（保留兼容）。"""

    return {
        "name": "AimeCard",
        "dsl": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "body": {
                "elements": [
                    {"tag": "markdown", "content": summary_md},
                    {"tag": "hr"},
                    {"tag": "markdown", "content": detail_md},
                ]
            },
        },
    }


# -----------------------------
# A 款（简约直达风）卡片模板
# -----------------------------

# 重要：这类“任务 DDL 巡检报警”的“工作站链接”必须指向【任务台账 / 个人工作站】。
TASK_WORKSTATION_TOKEN = "Yl6lwic1EiF2d3kHnzccZinsnLV"


def default_task_workstation_url(token: str = TASK_WORKSTATION_TOKEN) -> str:
    """将 token 组装成可跳转的工作站 URL。

    说明：该 token 可能来自“电子表格 / 多维表格”。
    这里默认组装为 sheets URL；如实际为多维表格，可改为 base 链接。
    """

    # 如果是特指的 BD 任务库，直接返回 Wiki 挂载链接
    if token == TASK_WORKSTATION_TOKEN:
        return "https://bytedance.larkoffice.com/wiki/Yl6lwic1EiF2d3kHnzccZinsnLV?sheet=KmlJhs"

    # - Spreadsheet: https://bytedance.larkoffice.com/sheets/<token>
    # - Bitable:     https://bytedance.larkoffice.com/base/<token>
    return f"https://bytedance.larkoffice.com/sheets/{token}"


def build_patrol_card_a(
    *,
    title: str,
    template: str,
    body_md: str,
    action_text: str,
    action_url: str,
) -> Dict[str, Any]:
    """飞书互动卡片（schema 2.0）- A 款简约直达风。

    结构：
    - Header：标题
    - Body：一段 markdown
    - Footer：一个跳转按钮
    """

    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": body_md},
        {"tag": "hr"},
        {
            "tag": "button",
            "type": "primary",
            "text": {"tag": "plain_text", "content": action_text},
            "behaviors": [
                {
                    "type": "open_url",
                    "default_url": action_url,
                }
            ],
        },
    ]

    return {
        "name": "AimeCard",
        "dsl": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "body": {
                "elements": elements,
            },
        },
    }


def _at_in_post(open_id: Optional[str], display_name: str) -> str:
    """Post（md 标签）里可用的 @ 语法。

    参考：飞书 post 的 md tag 支持 `<at user_id="ou_xxx">Name</at>`。
    """

    if open_id:
        return f'<at user_id="{open_id}">{display_name}</at>'
    return f"@{display_name}"


def _render_scheme3_message(
    items: Sequence[PatrolFinding],
    *,
    route_owner: Optional[OwnerIdentity] = None,
    include_due_soon: bool = True,
) -> str:
    """排版方案三：按异常类型聚合。

    目标输出样式（示例）：
    🔴 **【已超期】（请立即跟进）**
    - `任务名` (超期X天) ➡️ @责任人
    🟡 **【缺失 DDL】（请补全截止时间）**
    - `任务名` ➡️ @责任人
    🟣 **【格式异常 / 缺负责人】（请管理员 @于奇楠 协助核对）**
    - `任务名` (异常原因)

    说明：
    - 私聊分发场景下，为避免在私聊里“@到其他协作者”，默认只指向 route_owner。
    - 管理员汇总/兜底场景（route_owner=None）时，会展示该任务的全部负责人（如可得）。
    """

    def owner_hint(it: PatrolFinding) -> str:
        if route_owner is not None:
            return _at_in_post(route_owner.open_id, route_owner.display_name)
        if it.owners:
            return "、".join(_at_in_post(o.open_id, o.display_name) for o in it.owners)
        return "⚠️未分配"

    # 稳定排序：优先行号，其次任务名
    ordered = sorted(items, key=lambda x: (x.row if x.row is not None else 10**9, x.task))

    groups: Dict[str, List[PatrolFinding]] = {
        "overdue": [],
        "missing_ddl": [],
        "format_error": [],
        "due_soon": [],
    }
    for it in ordered:
        groups.setdefault(it.issue_type, []).append(it)

    lines: List[str] = []

    if groups.get("overdue"):
        lines.append("🔴 **【已超期】（请立即跟进）**")
        for it in groups["overdue"]:
            days = it.overdue_days
            if days is None and it.delta_days is not None:
                days = -it.delta_days
            days_show = f"超期{days}天" if days is not None else "已超期"
            lines.append(f"- `{it.task}` ({days_show}) ➡️ {owner_hint(it)}")

    if groups.get("missing_ddl"):
        lines.append("\n🟡 **【缺失 DDL】（请补全截止时间）**")
        for it in groups["missing_ddl"]:
            lines.append(f"- `{it.task}` ➡️ {owner_hint(it)}")

    if groups.get("format_error"):
        lines.append("\n🟣 **【格式异常 / 缺负责人】（请管理员 @于奇楠 协助核对）**")
        for it in groups["format_error"]:
            lines.append(f"- `{it.task}` ({it.reason})")

    if include_due_soon and groups.get("due_soon"):
        lines.append("\n🟠 **【临近到期】（请注意推进节奏）**")
        for it in groups["due_soon"]:
            if it.delta_days is not None:
                days_show = "今天到期" if it.delta_days == 0 else f"还有{it.delta_days}天"
                lines.append(f"- `{it.task}` ({days_show}) ➡️ {owner_hint(it)}")
            else:
                lines.append(f"- `{it.task}` ➡️ {owner_hint(it)}")

    return "\n".join(lines).strip()


def _render_task_blocks(
    items: Sequence[PatrolFinding],
    *,
    include_owner: bool,
    include_due_soon: bool = True,
) -> Tuple[str, List[str]]:
    """（旧版卡片渲染保留）渲染任务块，并按分类规则聚合，返回 (markdown, mentions_open_ids)。

    说明：卡片目前仍沿用原“逐条任务块”样式，避免一次改动影响卡片交互/组件上限。
    在此基础上增加了分类（如：已超期、缺失 DDL）的小标题区隔。
    路由层实际私聊分发将优先使用 `_render_scheme3_message` 的文本消息。
    """

    lines: List[str] = []
    mentions: List[str] = []
    _seen_mentions: set[str] = set()

    # 按照定义的优先级顺序进行分类展示
    category_order = ["已超期", "缺失 DDL", "临近到期", "格式异常"]
    if not include_due_soon:
        category_order = [c for c in category_order if c != "临近到期"]
    
    # 稳定排序：优先行号，其次任务名
    ordered = sorted(items, key=lambda x: (x.row if x.row is not None else 10**9, x.task))
    
    grouped: Dict[str, List[PatrolFinding]] = {cat: [] for cat in category_order}
    for it in ordered:
        cat = it.alert_category
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(it)

    for cat in category_order + [k for k in grouped.keys() if k not in category_order]:
        cat_items = grouped.get(cat, [])
        if not cat_items:
            continue
            
        # 分类标题
        if cat == "已超期":
            lines.append(f"\n🔴 **【{cat}】**")
        elif cat == "缺失 DDL":
            lines.append(f"\n🟡 **【{cat}】**")
        elif cat == "格式异常":
            lines.append(f"\n🟣 **【{cat}】**")
        elif cat == "临近到期":
            lines.append(f"\n🟠 **【{cat}】**")
        else:
            lines.append(f"\n⚪️ **【{cat}】**")

        for it in cat_items:
            ddl = it.ddl_parsed or _normalize_text(it.ddl_raw) or "无"
    
            # 关键：在 `📌 **【任务名】**` 前强制加一个换行符，确保不同任务间有空行区隔。
            lines.append(f"\n📌 **【任务名】**：{it.task}")
    
            if include_owner:
                if it.owners:
                    owners_show: List[str] = []
                    for o in it.owners:
                        owners_show.append(_at_in_card(o.open_id, o.display_name))
                        if o.open_id and o.open_id not in _seen_mentions:
                            mentions.append(o.open_id)
                            _seen_mentions.add(o.open_id)
                    lines.append(f"👤 **负责人**：{'、'.join(owners_show)}")
                else:
                    lines.append("👤 **负责人**：未分配")
    
            if it.issue_type == "overdue" and it.overdue_days is not None:
                lines.append(f"⏰ **DDL**：{ddl}（已超期 {it.overdue_days} 天）")
            elif it.issue_type == "due_soon" and it.delta_days is not None:
                lines.append(f"⏰ **DDL**：{ddl}（距离 {it.delta_days} 天）")
            elif it.issue_type in {"missing_ddl", "format_error"} and it.abnormal_days is not None:
                lines.append(f"⏰ **DDL**：{ddl}（连续 {it.abnormal_days} 天异常：{it.reason}）")
            else:
                lines.append(f"⏰ **DDL**：{ddl}（{it.reason}）")
    
            lines.append(f"🧭 **分类**：{it.alert_category}")

    return "\n".join(lines).strip(), mentions


# -----------------------------
# 巡检引擎
# -----------------------------


class TaskPatrol:
    """对【任务库】做 DDL 对账巡查，并生成“告警词典”。"""

    DEFAULT_CATEGORY_ORDER = ["临近到期", "已超期", "缺失 DDL", "格式异常"]

    def __init__(
        self,
        *,
        due_soon_days: int = 2,
        owner_resolver: Optional[Callable[[str], OwnerIdentity]] = None,
        private_overdue_max_days: int = 2,
        abnormal_private_max_days: int = 2,
        group_card_max_items_per_group: int = DEFAULT_COMPACT_CARD_MAX_ITEMS_PER_GROUP,
        group_card_only_changed: bool = False,
        group_card_previous_snapshot: Optional[Dict[str, str]] = None,
    ):
        if group_card_max_items_per_group <= 0:
            raise ValueError("group_card_max_items_per_group 必须为正整数")

        self.due_soon_days = due_soon_days
        self.private_overdue_max_days = private_overdue_max_days
        self.abnormal_private_max_days = abnormal_private_max_days
        self.owner_resolver = owner_resolver or (lambda raw: OwnerIdentity(raw=raw, display_name=raw, source="sheet"))
        self.group_card_max_items_per_group = group_card_max_items_per_group
        self.group_card_only_changed = group_card_only_changed
        self.group_card_previous_snapshot = dict(group_card_previous_snapshot or {})

    def _make_key(self, row_no: int, task: str) -> str:
        # 用户要求“基于行号或任务名防抖”：这里采用 row+task 的组合 key
        # 避免纯 row（插行会漂移），也避免纯 task（同名任务冲突）
        return f"r{row_no}:{task.strip()}"

    def classify(self, row: Dict[str, Any], today: date) -> Optional[PatrolFinding]:
        # 兼容两种 key：直接用表头名；或经过上游归一化
        owner_text = _normalize_text(row.get("负责人") or row.get("owner"))
        task = _normalize_text(row.get("交付结果") or row.get("task"))
        status = _normalize_text(row.get("完成情况") or row.get("status"))
        ddl_raw = row.get("DDL") if "DDL" in row else row.get("ddl")

        row_no = row.get("__row_number")
        row_no = int(row_no) if row_no is not None else -1

        if is_done(status):
            return None

        # 空行/表头行过滤
        if not task or task == "交付结果":
            return None

        key = self._make_key(row_no, task)

        # 负责人为空 -> 格式异常
        people = split_people(owner_text)
        if not people:
            return PatrolFinding(
                key=key,
                row=row_no,
                task=task,
                status=status,
                owners=[],
                ddl_raw=ddl_raw,
                ddl_parsed=None,
                delta_days=None,
                alert_category="格式异常",
                reason="负责人为空",
                issue_type="format_error",
            )

        owners = [self.owner_resolver(p) for p in people]

        parsed_ddl, parse_error = parse_ddl(ddl_raw, today=today)
        if parsed_ddl is None:
            # empty -> 缺失 DDL；其他 -> 格式异常
            if parse_error == "empty":
                category = "缺失 DDL"
                issue_type = "missing_ddl"
                reason = "DDL为空"
            else:
                category = "格式异常"
                issue_type = "format_error"
                reason = f"DDL无法解析（{parse_error}）"

            return PatrolFinding(
                key=key,
                row=row_no,
                task=task,
                status=status,
                owners=owners,
                ddl_raw=ddl_raw,
                ddl_parsed=None,
                delta_days=None,
                alert_category=category,
                reason=reason,
                issue_type=issue_type,
            )

        delta_days = (parsed_ddl - today).days
        if delta_days < 0:
            overdue_days = -delta_days
            return PatrolFinding(
                key=key,
                row=row_no,
                task=task,
                status=status,
                owners=owners,
                ddl_raw=ddl_raw,
                ddl_parsed=parsed_ddl.isoformat(),
                delta_days=delta_days,
                alert_category="已超期",
                reason="DDL早于今天",
                issue_type="overdue",
                overdue_days=overdue_days,
            )

        if 0 <= delta_days <= self.due_soon_days:
            return PatrolFinding(
                key=key,
                row=row_no,
                task=task,
                status=status,
                owners=owners,
                ddl_raw=ddl_raw,
                ddl_parsed=parsed_ddl.isoformat(),
                delta_days=delta_days,
                alert_category="临近到期",
                reason=f"DDL距离今天{delta_days}天",
                issue_type="due_soon",
            )

        return None

    def _apply_state_and_stage(self, it: PatrolFinding, today: date, state: Optional[PatrolStateStore]) -> PatrolFinding:
        # 只有“缺失 DDL / 格式异常”需要连续天数
        if state and it.issue_type in {"missing_ddl", "format_error"}:
            it.abnormal_days = state.bump(it.key, it.issue_type, today)
        elif state:
            # 任务恢复正常后，清理 state，避免误升级
            state.clear(it.key)

        # 两阶段路由策略
        if it.issue_type == "overdue" and it.overdue_days is not None:
            it.stage = "group" if it.overdue_days > self.private_overdue_max_days else "private"
        elif it.issue_type in {"missing_ddl", "format_error"} and it.abnormal_days is not None:
            it.stage = "group" if it.abnormal_days >= (self.abnormal_private_max_days + 1) else "private"
        else:
            # due_soon 或无法计算天数的兜底
            it.stage = "private"

        return it

    def build_output(
        self,
        findings: List[PatrolFinding],
        *,
        today: date,
        target_chat: Optional[Dict[str, Any]] = None,
        task_counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        grouped: "OrderedDict[str, List[PatrolFinding]]" = OrderedDict(
            (name, []) for name in self.DEFAULT_CATEGORY_ORDER
        )
        for item in findings:
            grouped.setdefault(item.alert_category, []).append(item)

        private_items = [x for x in findings if x.stage == "private"]
        group_items = [x for x in findings if x.stage == "group"]
        fixed_target_chat = default_broadcast_target_chat()

        # --- p2p：按 owner 分包（覆盖全部 findings，用于 Bot 私聊分发） ---
        p2p_routes: Dict[str, Dict[str, Any]] = {}
        for it in findings:
            if not it.owners:
                continue
            for o in it.owners:
                route_key = o.email or o.open_id or o.display_name
                if not route_key:
                    continue
                bucket = p2p_routes.setdefault(
                    route_key,
                    {
                        "owner": o.to_dict(),
                        "count": 0,
                        "items": [],
                        "message": "",
                        "card": None,
                        "mentions_open_ids": [],
                    },
                )
                bucket["count"] += 1
                bucket["items"].append(it.to_dict())

        # --- private：按 owner 分包（仅 private stage，用于兼容原两阶段策略） ---
        private_routes: Dict[str, Dict[str, Any]] = {}
        unmapped_bucket: List[PatrolFinding] = []
        for it in private_items:
            if not it.owners:
                unmapped_bucket.append(it)
                continue

            for o in it.owners:
                # 优先用 email/open_id 做路由 key，避免同名冲突
                route_key = o.email or o.open_id or o.display_name
                if not route_key:
                    unmapped_bucket.append(it)
                    continue

                bucket = private_routes.setdefault(
                    route_key,
                    {
                        "owner": o.to_dict(),
                        "count": 0,
                        "items": [],
                        "message": "",
                        "card": None,
                        "mentions_open_ids": [],
                    },
                )
                bucket["count"] += 1
                bucket["items"].append(it.to_dict())

        # 生成 message/card（p2p：用于 Bot 私聊分发，覆盖全部 findings）
        for route_key, bucket in p2p_routes.items():
            owner = bucket["owner"]

            owner_obj = OwnerIdentity(
                raw=str(owner.get("raw") or owner.get("display_name") or ""),
                display_name=str(owner.get("display_name") or owner.get("raw") or ""),
                open_id=owner.get("open_id"),
                email=owner.get("email"),
                source=str(owner.get("source") or "sheet"),
            )

            items_for_owner: List[PatrolFinding] = []
            for it in findings:
                if any((o.email or o.open_id or o.display_name) == route_key for o in it.owners):
                    items_for_owner.append(it)

            body_md = _render_scheme3_message(items_for_owner, route_owner=owner_obj)
            header = f"📌 **任务巡检提醒**（{today.isoformat()}，共 {bucket['count']} 条）"
            bucket["message"] = (header + "\n\n" + body_md).strip() if body_md else header

            detail_md, mentions = _render_task_blocks(items_for_owner, include_owner=False)
            bucket["mentions_open_ids"] = mentions

            workstation_url = default_task_workstation_url()
            body_md_for_card = (
                f"**日期**：{today.isoformat()}\n\n**需关注条目**：{bucket['count']}" + "\n\n" + (detail_md or "（无）")
            ).strip()
            bucket["card"] = build_patrol_card_a(
                title="📌 任务巡检提醒",
                template="blue",
                body_md=body_md_for_card,
                action_text="前往任务工作站处理",
                action_url=workstation_url,
            )

        # 生成 message/card（private：仅 private stage，用于兼容原两阶段策略）
        for route_key, bucket in private_routes.items():
            owner = bucket["owner"]

            owner_obj = OwnerIdentity(
                raw=str(owner.get("raw") or owner.get("display_name") or ""),
                display_name=str(owner.get("display_name") or owner.get("raw") or ""),
                open_id=owner.get("open_id"),
                email=owner.get("email"),
                source=str(owner.get("source") or "sheet"),
            )

            # 为保证输出稳定，我们从本次 findings 中重新筛出该 owner 的条目：
            items_for_owner: List[PatrolFinding] = []
            for it in private_items:
                if any((o.email or o.open_id or o.display_name) == route_key for o in it.owners):
                    items_for_owner.append(it)

            # message：排版方案三（按异常类型聚合）
            body_md = _render_scheme3_message(items_for_owner, route_owner=owner_obj)
            header = f"📌 **任务巡检提醒**（{today.isoformat()}，共 {bucket['count']} 条）"
            bucket["message"] = (header + "\n\n" + body_md).strip() if body_md else header

            # card：A 款简约直达风（用于飞书群聊/私聊统一渲染）
            detail_md, mentions = _render_task_blocks(items_for_owner, include_owner=False)
            bucket["mentions_open_ids"] = mentions

            workstation_url = default_task_workstation_url()
            body_md_for_card = (
                f"**日期**：{today.isoformat()}\n\n**需关注条目**：{bucket['count']}" + "\n\n" + (detail_md or "（无）")
            ).strip()
            bucket["card"] = build_patrol_card_a(
                title="📌 任务巡检提醒",
                template="blue",
                body_md=body_md_for_card,
                action_text="前往任务工作站处理",
                action_url=workstation_url,
            )

        # --- group：合并一包，发群并 @ ---
        _, group_mentions = _render_task_blocks(group_items, include_owner=True, include_due_soon=False)
        group_body_md = _render_scheme3_message(group_items, route_owner=None, include_due_soon=False)
        group_message_header = f"📣 **任务巡检·公开提醒**（{today.isoformat()}，共 {len(group_items)} 条）"
        group_card, group_card_meta = build_compact_patrol_card_a(
            items=group_items,
            today=today,
            title="📌 任务巡检提醒",
            template="red",
            summary_label="需公开提醒条目",
            action_text="前往任务工作站处理",
            action_url=default_task_workstation_url(),
            max_items_per_group=self.group_card_max_items_per_group,
            only_changed=False,
        )
        group_route = {
            "target_chat": fixed_target_chat,
            "count": len(group_items),
            "items": [it.to_dict() for it in group_items],
            "mentions_open_ids": group_mentions,
            "message": (group_message_header + "\n\n" + group_body_md).strip() if group_items else "",
            "card": group_card,
            "card_meta": group_card_meta,
        }

        # --- group_broadcast：全量 findings 过滤掉“临近到期”后合并一包，供“只发群聊、不做私聊”场景使用 ---
        broadcast_items = [it for it in findings if it.issue_type != "due_soon"]
        _, broadcast_mentions = _render_task_blocks(broadcast_items, include_owner=True, include_due_soon=False)
        broadcast_body_md = _render_scheme3_message(broadcast_items, route_owner=None, include_due_soon=False)
        broadcast_message_header = f"📌 **任务巡检提醒**（{today.isoformat()}，共 {len(broadcast_items)} 条）"
        broadcast_card, broadcast_card_meta = build_compact_patrol_card_a(
            items=broadcast_items,
            today=today,
            title="📌 任务巡检提醒",
            template="blue",
            summary_label="异常任务",
            action_text="前往任务工作站处理",
            action_url=default_task_workstation_url(),
            max_items_per_group=self.group_card_max_items_per_group,
            only_changed=self.group_card_only_changed,
            previous_snapshot=self.group_card_previous_snapshot,
        )
        broadcast_route = {
            "target_chat": fixed_target_chat,
            "count": len(broadcast_items),
            "items": [it.to_dict() for it in findings],  # 原数据结构仍保留全量（含临近到期）
            "mentions_open_ids": broadcast_mentions,
            "message": (broadcast_message_header + "\n\n" + broadcast_body_md).strip() if broadcast_items else "",
            "card": broadcast_card,
            "card_meta": broadcast_card_meta,
        }

        # --- unmapped：无法按邮箱/open_id 形成私聊分包的兜底桶 ---
        unmapped_body_md = _render_scheme3_message(unmapped_bucket, route_owner=None)
        unmapped_message_header = f"🧯 **任务巡检·未映射负责人兜底**（{today.isoformat()}，共 {len(unmapped_bucket)} 条）"

        # --- admin：格式异常/缺负责人（私聊给管理员） ---
        admin_items: List[PatrolFinding] = []
        _seen_admin: set[str] = set()
        for it in findings:
            if it.issue_type != "format_error" and it.owners:
                continue
            if it.key in _seen_admin:
                continue
            _seen_admin.add(it.key)
            admin_items.append(it)

        admin_body_md = _render_scheme3_message(admin_items, route_owner=None, include_due_soon=False)
        admin_message_header = f"🛠️ **任务巡检·管理员兜底**（{today.isoformat()}，共 {len(admin_items)} 条）"

        summary = {
            "today": today.isoformat(),
            "total_findings": len(findings),
            "counts": {k: len(v) for k, v in grouped.items()},
            "private_count": len(private_items),
            "group_count": len(group_items),
            "task_counts": task_counts or {"开启": 0, "完成": 0, "暂停": 0},
        }

        return {
            "summary": summary,
            "card_state": {
                "snapshot": broadcast_card_meta.get("snapshot", {}),
                "only_changed": self.group_card_only_changed,
                "max_items_per_group": self.group_card_max_items_per_group,
                "target_chat": fixed_target_chat,
            },
            "grouped_results": {k: [it.to_dict() for it in v] for k, v in grouped.items()},
            "routes": {
                "p2p": p2p_routes,
                "private": private_routes,
                "group_broadcast": broadcast_route,
                "group": group_route,
                "unmapped": {
                    "count": len(unmapped_bucket),
                    "items": [it.to_dict() for it in unmapped_bucket],
                    "message": (
                        (unmapped_message_header + "\n\n" + unmapped_body_md).strip()
                        if unmapped_bucket
                        else ""
                    ),
                },
                "admin": {
                    "count": len(admin_items),
                    "items": [it.to_dict() for it in admin_items],
                    "message": (
                        (admin_message_header + "\n\n" + admin_body_md).strip()
                        if admin_items
                        else ""
                    ),
                },
            },
        }

    def run(
        self,
        rows: Iterable[Dict[str, Any]],
        *,
        today: Optional[date] = None,
        state: Optional[PatrolStateStore] = None,
        target_chat: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        today = today or date.today()

        findings: List[PatrolFinding] = []
        task_counts = {"开启": 0, "完成": 0, "暂停": 0}
        
        # 将 Iterable 转为 list 方便多次遍历，或在一次遍历中处理
        # 考虑到性能和逻辑清晰度，我们在一次遍历中完成统计与巡检
        for r in rows:
            # 统计全量任务状态
            status = _normalize_text(r.get("完成情况") or r.get("status"))
            if is_started(status):
                task_counts["开启"] += 1
            elif is_done(status):
                task_counts["完成"] += 1
            elif is_paused(status):
                task_counts["暂停"] += 1

            # 巡检逻辑
            item = self.classify(r, today=today)
            if item is None:
                continue
            findings.append(self._apply_state_and_stage(item, today=today, state=state))

        return self.build_output(findings, today=today, target_chat=target_chat, task_counts=task_counts)
