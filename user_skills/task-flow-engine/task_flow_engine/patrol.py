import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


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
    """从【团队联系方式】Sheet 的行字典构建负责人映射。

    约定：
    - 用 `中文名称` 列来匹配【任务库】里的“负责人”（匹配时会做 `_normalize_person_key` 归一化）。
    - 产出 `OwnerIdentity.open_id` 与 `OwnerIdentity.email`，供后续告警路由使用（私聊优先 email）。

    返回：
    - owner_directory: {normalized_name -> OwnerIdentity}
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

        out[key] = OwnerIdentity(
            raw=raw_name,
            display_name=raw_name,
            open_id=open_id,
            email=email,
            source="sheet_roster",
        )

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
TASK_WORKSTATION_TOKEN = "TnNYsLq9phIJwutJGwBl730ygjd"


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
    ):
        self.due_soon_days = due_soon_days
        self.private_overdue_max_days = private_overdue_max_days
        self.abnormal_private_max_days = abnormal_private_max_days
        self.owner_resolver = owner_resolver or (lambda raw: OwnerIdentity(raw=raw, display_name=raw, source="sheet"))

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
    ) -> Dict[str, Any]:
        grouped: "OrderedDict[str, List[PatrolFinding]]" = OrderedDict(
            (name, []) for name in self.DEFAULT_CATEGORY_ORDER
        )
        for item in findings:
            grouped.setdefault(item.alert_category, []).append(item)

        private_items = [x for x in findings if x.stage == "private"]
        group_items = [x for x in findings if x.stage == "group"]

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
        group_detail_md, group_mentions = _render_task_blocks(group_items, include_owner=True)
        group_body_md = _render_scheme3_message(group_items, route_owner=None)
        group_message_header = f"📣 **任务巡检·公开提醒**（{today.isoformat()}，共 {len(group_items)} 条）"
        group_route = {
            "target_chat": target_chat,
            "count": len(group_items),
            "items": [it.to_dict() for it in group_items],
            "mentions_open_ids": group_mentions,
            "message": (group_message_header + "\n\n" + group_body_md).strip() if group_items else "",
            "card": (
                build_patrol_card_a(
                    title="📌 任务巡检提醒",
                    template="red",
                    body_md=(
                        f"**日期**：{today.isoformat()}\n\n**需公开提醒条目**：{len(group_items)}"
                        + "\n\n"
                        + (group_detail_md or "（无）")
                    ).strip(),
                    action_text="前往任务工作站处理",
                    action_url=default_task_workstation_url(),
                )
                if group_items
                else None
            ),
        }

        # --- group_broadcast：全量 findings 合并一包，供“只发群聊、不做私聊”场景使用 ---
        broadcast_detail_md, broadcast_mentions = _render_task_blocks(findings, include_owner=True)
        broadcast_body_md = _render_scheme3_message(findings, route_owner=None)
        broadcast_message_header = f"📌 **任务巡检提醒**（{today.isoformat()}，共 {len(findings)} 条）"
        broadcast_route = {
            "target_chat": target_chat,
            "count": len(findings),
            "items": [it.to_dict() for it in findings],
            "mentions_open_ids": broadcast_mentions,
            "message": (broadcast_message_header + "\n\n" + broadcast_body_md).strip() if findings else "",
            "card": (
                build_patrol_card_a(
                    title="📌 任务巡检提醒",
                    template="blue",
                    body_md=(
                        f"**日期**：{today.isoformat()}\n\n**异常任务**：{len(findings)}"
                        + "\n\n"
                        + (broadcast_detail_md or "（无）")
                    ).strip(),
                    action_text="前往任务工作站处理",
                    action_url=default_task_workstation_url(),
                )
                if findings
                else None
            ),
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
        }

        return {
            "summary": summary,
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
        for r in rows:
            item = self.classify(r, today=today)
            if item is None:
                continue
            findings.append(self._apply_state_and_stage(item, today=today, state=state))

        return self.build_output(findings, today=today, target_chat=target_chat)
