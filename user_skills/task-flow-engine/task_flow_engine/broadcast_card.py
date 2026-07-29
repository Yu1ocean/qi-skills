from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import pandas as pd


CATEGORY_ORDER: List[str] = ["已超期", "临近到期", "缺失 DDL", "格式异常"]
FOCUS_PRIORITY_ORDER: List[str] = ["已超期", "缺失 DDL", "格式异常", "临近到期"]
CATEGORY_ICONS: Dict[str, str] = {
    "已超期": "🔴",
    "临近到期": "🔵",
    "缺失 DDL": "🟡",
    "格式异常": "🟣",
}
HIGH_PRIORITY_CATEGORIES = {"已超期", "缺失 DDL", "格式异常"}
CATEGORY_CELL_COLORS: Dict[str, str] = {
    "已超期": "#FDECEC",
    "缺失 DDL": "#FFF7E0",
    "格式异常": "#F3E8FF",
    "临近到期": "#E8F2FF",
    "合计": "#F3F4F6",
}
UNASSIGNED_OWNER_KEY = "__unassigned__"


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _card_at(open_id: Optional[str], display_name: str) -> str:
    if open_id:
        return f'<at id="{open_id}"></at>'
    return f"@{display_name}"


def _owner_identity(owner: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    owner = owner or {}
    display_name = (
        _safe_text(owner.get("display_name"))
        or _safe_text(owner.get("raw"))
        or _safe_text(owner.get("name"))
        or "未分配"
    )
    route_key = (
        _safe_text(owner.get("email"))
        or _safe_text(owner.get("open_id"))
        or display_name
    )
    if display_name == "未分配":
        route_key = UNASSIGNED_OWNER_KEY
    return {
        "route_key": route_key,
        "display_name": display_name,
        "open_id": _safe_text(owner.get("open_id")) or None,
        "email": _safe_text(owner.get("email")) or None,
        "is_unassigned": route_key == UNASSIGNED_OWNER_KEY,
    }


def _iter_grouped_alert_items(alerts: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    grouped = alerts.get("grouped_results") or {}
    if not isinstance(grouped, dict):
        return []

    ordered_categories = [name for name in CATEGORY_ORDER if isinstance(grouped.get(name), list)]
    ordered_categories += [
        name for name, items in grouped.items() if name not in ordered_categories and isinstance(items, list)
    ]

    flattened: List[Dict[str, Any]] = []
    for category in ordered_categories:
        for item in grouped.get(category) or []:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized.setdefault("alert_category", category)
            flattened.append(normalized)
    return flattened


def extract_broadcast_alert_items(alerts: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = list(_iter_grouped_alert_items(alerts))
    if items:
        return items

    route = ((alerts.get("routes") or {}).get("group_broadcast") or {})
    flattened: List[Dict[str, Any]] = []
    for item in route.get("items") or []:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        flattened.append(normalized)
    return flattened


def _category_priority_tuple(bucket: Dict[str, Any]) -> Tuple[int, int, int, int, int, str]:
    counts = bucket.get("counts") or {}
    priority = tuple(-int(counts.get(category) or 0) for category in FOCUS_PRIORITY_ORDER)
    return (*priority, -int(bucket.get("total") or 0), str(bucket.get("display_name") or ""))


def aggregate_owner_alert_stats(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for item in items:
        category = _safe_text(item.get("alert_category")) or "未知类型"
        owners = item.get("owners") if isinstance(item.get("owners"), list) else []
        owner_list = owners or [None]
        for owner in owner_list:
            identity = _owner_identity(owner if isinstance(owner, dict) else None)
            bucket = buckets.setdefault(
                identity["route_key"],
                {
                    "route_key": identity["route_key"],
                    "display_name": identity["display_name"],
                    "open_id": identity["open_id"],
                    "email": identity["email"],
                    "is_unassigned": identity["is_unassigned"],
                    "counts": OrderedDict((name, 0) for name in CATEGORY_ORDER),
                    "total": 0,
                },
            )
            bucket["counts"].setdefault(category, 0)
            bucket["counts"][category] += 1
            bucket["total"] += 1
    return sorted(buckets.values(), key=_category_priority_tuple)


def pick_top_focus_owners(items: Sequence[Dict[str, Any]], *, top_n: int = 3) -> List[Dict[str, Any]]:
    buckets = aggregate_owner_alert_stats(items)
    picked: List[Dict[str, Any]] = []
    for bucket in buckets:
        if bucket.get("is_unassigned"):
            continue
        picked.append(bucket)
        if len(picked) >= top_n:
            break
    return picked


def build_stats_dataframe(items: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    buckets = aggregate_owner_alert_stats(items)
    columns = ["负责人", *CATEGORY_ORDER, "合计"]
    if not buckets:
        return pd.DataFrame(columns=columns)

    rows: List[Dict[str, Any]] = []
    for bucket in buckets:
        total = int(bucket.get("total") or 0)
        if total <= 0:
            continue
        row = {"负责人": bucket["display_name"]}
        for category in CATEGORY_ORDER:
            row[category] = int(bucket.get("counts", {}).get(category) or 0)
        row["合计"] = total
        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def build_summary_counts(items: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = OrderedDict((name, 0) for name in CATEGORY_ORDER)
    for item in items:
        category = _safe_text(item.get("alert_category")) or "未知类型"
        counts.setdefault(category, 0)
        counts[category] += 1
    return counts


def render_owner_category_table_image(
    *,
    items: Sequence[Dict[str, Any]],
    today_text: str,
    output_path: Path,
    top_focus_owners: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe = build_stats_dataframe(items)
    top_focus_names = {str(owner.get("display_name") or "") for owner in (top_focus_owners or [])}

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC"] + list(plt.rcParams.get("font.sans-serif", []))
    plt.rcParams["axes.unicode_minus"] = False

    if dataframe.empty:
        fig, ax = plt.subplots(figsize=(10, 2.8), dpi=220)
        fig.subplots_adjust(top=0.72, bottom=0.12)
        fig.suptitle("任务巡检异常统计总览", fontsize=16, fontweight="bold")
        fig.text(0.5, 0.88, f"日期：{today_text}｜今日无异常任务", ha="center", fontsize=10)
        ax.axis("off")
        ax.text(0.5, 0.5, "今日无异常任务", ha="center", va="center", fontsize=14)
        fig.savefig(output_path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return {
            "image_path": str(output_path),
            "row_count": 0,
            "column_count": int(len(dataframe.columns)),
            "summary_counts": build_summary_counts(items),
        }

    figure_width = max(10.0, 2.2 * len(dataframe.columns) + 1.0)
    figure_height = max(2.8, 0.45 * (len(dataframe) + 2) + 1.2)
    fig, ax = plt.subplots(figsize=(figure_width, figure_height), dpi=220)
    fig.subplots_adjust(top=0.82, bottom=0.02)
    fig.suptitle("任务巡检异常统计总览", fontsize=16, fontweight="bold", y=0.94)
    fig.text(
        0.5,
        0.86,
        f"日期：{today_text}｜纵轴：负责人｜横轴：异常分类｜单元格：数量",
        ha="center",
        fontsize=10,
    )
    ax.axis("off")

    table = ax.table(
        cellText=dataframe.values,
        colLabels=list(dataframe.columns),
        cellLoc="center",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 1.2)

    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_edgecolor("#D1D5DB")
        if row_index == 0:
            cell.set_facecolor("#E8F1FF")
            cell.get_text().set_fontweight("bold")
            cell.get_text().set_color("#1F2937")
            continue

        owner_name = str(dataframe.iloc[row_index - 1, 0])
        column_name = str(dataframe.columns[col_index])
        cell.get_text().set_color("#111827")
        if col_index == 0:
            cell.get_text().set_ha("left")
            if owner_name in top_focus_names:
                cell.set_facecolor("#FFF4D6")
                cell.get_text().set_fontweight("bold")
            elif owner_name == "未分配":
                cell.set_facecolor("#F3F4F6")
            else:
                cell.set_facecolor("#FFFFFF")
            continue

        raw_value = dataframe.iloc[row_index - 1, col_index]
        value = int(raw_value) if str(raw_value).strip() else 0
        base_color = CATEGORY_CELL_COLORS.get(column_name, "#FFFFFF")
        if value <= 0:
            cell.set_facecolor("#FFFFFF")
        elif owner_name in top_focus_names:
            cell.set_facecolor(base_color)
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(base_color)

    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {
        "image_path": str(output_path),
        "row_count": int(len(dataframe)),
        "column_count": int(len(dataframe.columns)),
        "summary_counts": build_summary_counts(items),
        "top_focus_names": list(top_focus_names),
    }


def _format_focus_owner_mention(owner: Dict[str, Any]) -> str:
    return _card_at(owner.get("open_id"), str(owner.get("display_name") or "同学"))


def _format_focus_owner_line(owner: Dict[str, Any]) -> str:
    mention = _format_focus_owner_mention(owner)
    counts = owner.get("counts") if isinstance(owner.get("counts"), dict) else {}
    risk_parts: List[str] = []
    for category in FOCUS_PRIORITY_ORDER:
        count = int(counts.get(category) or 0)
        if count <= 0:
            continue
        icon = CATEGORY_ICONS.get(category, "•")
        weight = "‼️" if category in HIGH_PRIORITY_CATEGORIES else "•"
        risk_parts.append(f"{weight}{icon}{category}×{count}")
    risk_summary = " / ".join(risk_parts) if risk_parts else f"合计×{int(owner.get('total') or 0)}"
    return f"🚨 **{mention}**｜{risk_summary}"


def build_minimal_broadcast_card(
    *,
    today_text: str,
    summary_counts: Dict[str, int],
    top_focus_owners: Sequence[Dict[str, Any]],
    action_text: str,
    action_url: str,
    image_key: Optional[str] = None,
    title: str = "📌 任务巡检提醒",
    template: str = "blue",
) -> Dict[str, Any]:
    summary_parts = []
    for category in CATEGORY_ORDER:
        count = int(summary_counts.get(category) or 0)
        if count <= 0:
            continue
        icon = CATEGORY_ICONS.get(category, "•")
        summary_parts.append(f"{icon} **{category}** {count}")
    summary_line = " ｜ ".join(summary_parts) if summary_parts else "✅ **今日无异常任务**"

    if top_focus_owners:
        focus_body = "\n".join(_format_focus_owner_mention(owner) for owner in top_focus_owners)
    else:
        focus_body = "今日未识别出需要重点点名的负责人。"

    # v2.1.0：取消 ### 三级标题（飞书卡片中字号偏小且与正文区隔不明显），
    # 改为「正文加粗 + hr 分割线」的扁平结构，全文字号统一、视觉更清爽。
    date_md = f"**日期**：{today_text}"
    summary_md = "\n".join(["**📊 巡检统计**", summary_line])
    focus_md = "\n".join(["**📌 重点关注**", focus_body])
    overview_md = (
        "**🖼️ 异常总览表**\n"
        "负责人 × 异常分类（已超期 / 临近到期 / 缺失 DDL / 格式异常）"
    )

    elements: List[Dict[str, Any]] = [
        {"tag": "markdown", "content": date_md},
        {"tag": "hr"},
        {"tag": "markdown", "content": summary_md},
        {"tag": "hr"},
        {"tag": "markdown", "content": focus_md},
        {"tag": "hr"},
        {"tag": "markdown", "content": overview_md},
    ]
    if image_key:
        elements.append(
            {
                "tag": "img",
                "img_key": image_key,
                "mode": "fit_horizontal",
            }
        )
    else:
        elements.append(
            {
                "tag": "markdown",
                "content": "_异常总览表图片已在本地生成；真实发送时会嵌入卡片正文。_",
            }
        )
    elements.append(
        {
            "tag": "button",
            "type": "primary",
            "text": {"tag": "plain_text", "content": action_text},
            "behaviors": [{"type": "open_url", "default_url": action_url}],
        }
    )

    return {
        "name": "AimeCard",
        "dsl": {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "body": {"elements": elements},
        },
    }
