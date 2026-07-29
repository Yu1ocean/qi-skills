from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

DEFAULT_TASKFLOW_SHEET_URL = "https://bytedance.larkoffice.com/sheets/TnNYsLq9phIJwutJGwBl730ygjd?sheet=KmlJhs"
DEFAULT_STATUS_TEXT = "✅ 已入库"
DEFAULT_OPEN_SHEET_TEXT = "打开任务库"


@dataclass(frozen=True)
class TaskflowAckRenderInput:
    task_name: str
    owner: str
    status: str = DEFAULT_STATUS_TEXT
    sheet_url: str = DEFAULT_TASKFLOW_SHEET_URL


def _clean_text(value: Any, fallback: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or fallback


def normalize_taskflow_ack_input(
    *,
    task_name: Any,
    owner: Any,
    status: Any = DEFAULT_STATUS_TEXT,
    sheet_url: Any = DEFAULT_TASKFLOW_SHEET_URL,
) -> TaskflowAckRenderInput:
    return TaskflowAckRenderInput(
        task_name=_clean_text(task_name, "未命名任务"),
        owner=_clean_text(owner, "待补充"),
        status=_clean_text(status, DEFAULT_STATUS_TEXT),
        sheet_url=_clean_text(sheet_url, DEFAULT_TASKFLOW_SHEET_URL),
    )


def render_taskflow_ack_text(
    *,
    task_name: Any,
    owner: Any,
    status: Any = DEFAULT_STATUS_TEXT,
    sheet_url: Any = DEFAULT_TASKFLOW_SHEET_URL,
    open_sheet_text: str = DEFAULT_OPEN_SHEET_TEXT,
) -> str:
    payload = normalize_taskflow_ack_input(
        task_name=task_name,
        owner=owner,
        status=status,
        sheet_url=sheet_url,
    )
    safe_open_sheet_text = _clean_text(open_sheet_text, DEFAULT_OPEN_SHEET_TEXT)
    return (
        f"已录入任务台账：{payload.task_name}｜负责人：{payload.owner}｜状态：{payload.status}｜"
        f"[{safe_open_sheet_text}]({payload.sheet_url})"
    )


def build_taskflow_ack_post(
    *,
    task_name: Any,
    owner: Any,
    status: Any = DEFAULT_STATUS_TEXT,
    sheet_url: Any = DEFAULT_TASKFLOW_SHEET_URL,
    open_sheet_text: str = DEFAULT_OPEN_SHEET_TEXT,
) -> Dict[str, Any]:
    payload = normalize_taskflow_ack_input(
        task_name=task_name,
        owner=owner,
        status=status,
        sheet_url=sheet_url,
    )
    prefix = (
        f"已录入任务台账：{payload.task_name}｜负责人：{payload.owner}｜状态：{payload.status}｜"
    )
    safe_open_sheet_text = _clean_text(open_sheet_text, DEFAULT_OPEN_SHEET_TEXT)
    return {
        "zh_cn": {
            "title": "",
            "content": [
                [
                    {"tag": "text", "text": prefix},
                    {"tag": "a", "text": safe_open_sheet_text, "href": payload.sheet_url},
                ]
            ],
        }
    }


def build_taskflow_ack_record(
    *,
    task_name: Any,
    owner: Any,
    status: Any = DEFAULT_STATUS_TEXT,
    sheet_url: Any = DEFAULT_TASKFLOW_SHEET_URL,
) -> Dict[str, str]:
    payload = normalize_taskflow_ack_input(
        task_name=task_name,
        owner=owner,
        status=status,
        sheet_url=sheet_url,
    )
    return {
        "task_name": payload.task_name,
        "owner": payload.owner,
        "status": payload.status,
        "sheet_url": payload.sheet_url,
        "rendered_text": render_taskflow_ack_text(
            task_name=payload.task_name,
            owner=payload.owner,
            status=payload.status,
            sheet_url=payload.sheet_url,
        ),
    }
