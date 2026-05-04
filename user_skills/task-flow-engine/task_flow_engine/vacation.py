from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from .patrol import OwnerIdentity, PatrolFinding, build_patrol_card, _render_task_blocks


def is_legal_rest_day(day: date) -> bool:
    """Return True if the given day is a legal public holiday in China.

    使用 ``chinese_calendar`` 库判断法定节假日。任何导入或运行时错误都视为
    "非节假日"（fail-open），避免打断主流程。
    """

    try:
        from chinese_calendar import is_holiday  # type: ignore[import]
    except Exception:
        return False

    try:
        return bool(is_holiday(day))
    except Exception:
        # 任何计算异常都视为工作日，避免错误放大
        return False


@dataclass
class _FreeBusySlot:
    start: datetime
    end: datetime

    @property
    def hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


class FeishuVacationClient:
    """Thin HTTP client for Feishu calendar freebusy API.

    设计目标：
    - 仅依赖标准库 ``urllib`` / ``json``，不额外引入第三方库
    - 默认使用 ``AIME_USER_CLOUD_JWT`` 作为 Authorization 头（Bearer），与
      当前仓库其它脚本的用法保持一致
    - 所有网络 / 解析错误一律 fail-open（返回 False），**绝不**中断巡检主流程
    """

    def __init__(self, base_url: Optional[str] = None, timeout: int = 5) -> None:
        # open 平台文档推荐使用 fsopen 域名
        self.base_url = (base_url or "https://fsopen.bytedance.net").rstrip("/")
        self.timeout = timeout

    # -------- public API --------

    def is_user_on_leave_by_freebusy(
        self,
        *,
        owner: OwnerIdentity,
        today: date,
        min_busy_hours: float = 4.0,
    ) -> bool:
        """Heuristic: treat user as "on leave" if busy for most of the day.

        实现思路：
        - 调用 ``/calendar/v4/freebusy/list`` 查询当天 0-24 点的忙闲
        - 累计所有忙碌区间在当天内的时长
        - 若总忙碌时长 >= ``min_busy_hours``，认为该用户处于 "OOTO/OnLeave" 状态

        约束与注意：
        - 只在 ``owner.open_id`` 存在时尝试调用 API；否则直接返回 False
        - 只使用 "open_id" 作为 user_id_type，避免过度复杂的 ID 映射
        - 所有网络错误 / JSON 解析错误 / 字段缺失都视为 "非请假"（fail-open）
        """

        if not owner.open_id:
            return False

        headers = self._build_auth_headers()
        if headers is None:
            return False

        # 以北京时间 0 点到次日 0 点作为一天的观察窗口
        # 这里不试图精确到员工时区，保持实现简单且稳定
        day_start = datetime.strptime(day.isoformat() + "T00:00:00+08:00", "%Y-%m-%dT%H:%M:%S%z")
        day_end = day_start + timedelta(days=1)

        url_path = "/open-apis/calendar/v4/freebusy/list"
        query = {"user_id_type": "open_id"}
        body = {
            "time_min": day_start.isoformat(),
            "time_max": day_end.isoformat(),
            "user_id": owner.open_id,
            "only_busy": True,
            # 包含第三方日历可以更完整地覆盖 HR 系统同步的请假日程
            "include_external_calendar": True,
            # 如有权限，可返回 RSVP 状态；即使没有权限也不会影响忙闲判定
            "need_rsvp_status": False,
        }

        try:
            payload = self._post_json(url_path, query=query, body=body, headers=headers)
        except Exception:
            return False

        if not payload:
            return False

        data = payload.get("data") or {}
        slots_raw = data.get("freebusy_list") or []
        if not isinstance(slots_raw, list):
            return False

        slots: List[_FreeBusySlot] = []
        for item in slots_raw:
            if not isinstance(item, dict):
                continue
            start_str = item.get("start_time")
            end_str = item.get("end_time")
            if not start_str or not end_str:
                continue
            try:
                s = datetime.fromisoformat(start_str)
                e = datetime.fromisoformat(end_str)
            except Exception:
                continue
            if e <= s:
                continue
            # 与当天窗口求交集
            if e <= day_start or s >= day_end:
                continue
            s_clamped = max(s, day_start)
            e_clamped = min(e, day_end)
            slots.append(_FreeBusySlot(start=s_clamped, end=e_clamped))

        total_busy_hours = sum(slot.hours for slot in slots)
        return total_busy_hours >= max(0.0, float(min_busy_hours))

    # -------- internal helpers --------

    def _build_auth_headers(self) -> Optional[Dict[str, str]]:
        token = os.environ.get("AIME_USER_CLOUD_JWT")
        if not token:
            return None
        if not token.startswith("Bearer "):
            token = f"Bearer {token}"
        return {
            "Authorization": token,
            "Content-Type": "application/json; charset=utf-8",
        }

    def _post_json(
        self,
        path: str,
        *,
        query: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        url = self.base_url + path
        if query:
            url = url + "?" + urlparse.urlencode(query)

        data_bytes = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(url, data=data_bytes, headers=headers or {}, method="POST")

        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8")
        except urlerror.URLError:
            return None
        except Exception:
            return None

        try:
            obj = json.loads(resp_body)
        except json.JSONDecodeError:
            return None

        code = obj.get("code")
        if code not in (0, "0", None):
            # 非 0 错误码一律视为失败，交由上层 fail-open
            return None
        return obj


OwnerOnLeaveChecker = Callable[[OwnerIdentity], bool]


def _dict_to_owner_identity(data: Dict[str, Any]) -> OwnerIdentity:
    return OwnerIdentity(
        raw=str(data.get("raw") or data.get("display_name") or ""),
        display_name=str(data.get("display_name") or data.get("raw") or ""),
        open_id=data.get("open_id"),
        email=data.get("email"),
        source=str(data.get("source") or "sheet"),
    )


def _dict_to_finding(data: Dict[str, Any]) -> PatrolFinding:
    owners_raw = data.get("owners") or []
    owners: List[OwnerIdentity] = []
    for o in owners_raw:
        if not isinstance(o, dict):
            continue
        owners.append(_dict_to_owner_identity(o))

    return PatrolFinding(
        key=str(data.get("key") or ""),
        row=int(data.get("row") or -1),
        task=str(data.get("task") or ""),
        status=data.get("status"),
        owners=owners,
        ddl_raw=data.get("ddl_raw"),
        ddl_parsed=data.get("ddl_parsed"),
        delta_days=data.get("delta_days"),
        alert_category=str(data.get("alert_category") or ""),
        reason=str(data.get("reason") or ""),
        issue_type=str(data.get("issue_type") or ""),
        overdue_days=data.get("overdue_days"),
        abnormal_days=data.get("abnormal_days"),
        stage=data.get("stage"),
    )


def apply_vacation_guard(
    output: Dict[str, Any],
    *,
    today: date,
    is_holiday: bool,
    owner_on_leave_checker: Optional[OwnerOnLeaveChecker] = None,
) -> Dict[str, Any]:
    """Apply "vacation skip & defer" policy to patrol routing output.

    约定：
    - "法定休息日"：通过 ``is_legal_rest_day`` 判定，命中后直接静默整天
    - "个人请假"：通过 ``owner_on_leave_checker`` 判定，每个负责人独立兜底
    - fail-open：无论是节假日库或飞书 API 调用失败，都不会中断主流程

    具体行为：
    - 若 ``is_holiday`` 为 True：
      - 清空 ``routes.private`` / ``routes.group`` / ``routes.unmapped``，仅保留统计与明细
      - 在 ``output["vacation"]`` 中记录本次静默信息
    - 否则：
      - 对每个私聊路由 bucket，根据负责人是否请假进行过滤
      - 对群聊公开提醒路由，过滤掉负责人处于请假的条目，并重建 message/card
      - "未映射"（unmapped）保持不变
    """

    routes = output.get("routes") or {}
    private_routes = routes.get("private") or {}
    group_route = routes.get("group") or {}
    unmapped_route = routes.get("unmapped") or {}

    skipped_private: List[Dict[str, Any]] = []
    skipped_group_items: List[Dict[str, Any]] = []

    # --- 全局法定节假日：直接静默整天 ---
    if is_holiday:
        if isinstance(private_routes, dict):
            for key, bucket in private_routes.items():
                skipped_private.append(
                    {
                        "route_key": key,
                        "owner": bucket.get("owner"),
                        "count": bucket.get("count"),
                    }
                )
        if isinstance(group_route, dict):
            for item in group_route.get("items") or []:
                if isinstance(item, dict):
                    skipped_group_items.append(
                        {
                            "key": item.get("key"),
                            "owners": item.get("owners"),
                        }
                    )

        routes["private"] = {}
        routes["group"] = {
            "target_chat": group_route.get("target_chat"),
            "count": 0,
            "items": [],
            "mentions_open_ids": [],
            "message": "",
            "card": None,
        }
        routes["unmapped"] = {"count": 0, "items": []}

        summary = output.get("summary") or {}
        if isinstance(summary, dict):
            summary["private_count"] = 0
            summary["group_count"] = 0
            output["summary"] = summary

        output["routes"] = routes
        output["vacation"] = {
            "date": today.isoformat(),
            "is_holiday": True,
            "personal_checker_enabled": bool(owner_on_leave_checker),
            "mode": "holiday_only",
            "skipped": {
                "private_route_keys": [x.get("route_key") for x in skipped_private],
                "group_item_keys": [x.get("key") for x in skipped_group_items],
            },
        }
        return output

    # --- 仅个人请假：按负责人维度过滤 ---
    if not owner_on_leave_checker:
        # 无个人请假检查器，直接标记并返回
        output["vacation"] = {
            "date": today.isoformat(),
            "is_holiday": False,
            "personal_checker_enabled": False,
        }
        return output

    # 使用简单缓存，避免对同一负责人重复调用 API
    leave_cache: Dict[str, bool] = {}

    def is_on_leave(owner: OwnerIdentity) -> bool:
        key = owner.email or owner.open_id or owner.display_name or owner.raw
        if not key:
            return False
        if key in leave_cache:
            return leave_cache[key]
        try:
            value = bool(owner_on_leave_checker(owner))
        except Exception:
            value = False
        leave_cache[key] = value
        return value

    # --- 1) 过滤私聊路由 ---
    new_private: Dict[str, Any] = {}
    if isinstance(private_routes, dict):
        for route_key, bucket in private_routes.items():
            owner_dict = bucket.get("owner") or {}
            owner = _dict_to_owner_identity(owner_dict) if isinstance(owner_dict, dict) else _dict_to_owner_identity({})
            if is_on_leave(owner):
                skipped_private.append(
                    {
                        "route_key": route_key,
                        "owner": owner_dict,
                        "count": bucket.get("count"),
                    }
                )
                continue
            new_private[route_key] = bucket

    # 为保守起见，重新渲染每个私聊 bucket 的 message/card
    for route_key, bucket in new_private.items():
        items_raw = bucket.get("items") or []
        findings_for_owner: List[PatrolFinding] = []
        for d in items_raw:
            if isinstance(d, dict):
                findings_for_owner.append(_dict_to_finding(d))

        if not findings_for_owner:
            # 理论上不会出现，但为了安全起见仍然处理
            bucket["count"] = 0
            bucket["message"] = ""
            bucket["card"] = None
            bucket["mentions_open_ids"] = []
            continue

        bucket["count"] = len(findings_for_owner)
        header = f"🚨 **[任务巡检·私聊催办] {today.isoformat()}**（共 {bucket['count']} 条）"
        detail_md, mentions = _render_task_blocks(findings_for_owner, include_owner=False)
        bucket["mentions_open_ids"] = mentions
        bucket["message"] = (header + "\n" + detail_md).strip()
        summary_md = f"**日期**：{today.isoformat()}\n\n**需关注条目**：{bucket['count']}"
        bucket["card"] = build_patrol_card(
            title="任务巡检提醒（私聊）",
            template="blue",
            summary_md=summary_md,
            detail_md=detail_md,
        )

    # --- 2) 过滤群聊公开提醒 ---
    new_group_items: List[Dict[str, Any]] = []
    if isinstance(group_route, dict):
        items = group_route.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            owners_raw = item.get("owners") or []
            owners: List[OwnerIdentity] = []
            for o in owners_raw:
                if not isinstance(o, dict):
                    continue
                owners.append(_dict_to_owner_identity(o))

            # 若至少一位负责人处于请假状态，则整体顺延该条目
            if owners and any(is_on_leave(o) for o in owners):
                skipped_group_items.append(
                    {
                        "key": item.get("key"),
                        "owners": owners_raw,
                    }
                )
                continue

            new_group_items.append(item)

    # 回写过滤后的路由
    routes["private"] = new_private

    if isinstance(group_route, dict):
        group_findings: List[PatrolFinding] = []
        for d in new_group_items:
            if isinstance(d, dict):
                group_findings.append(_dict_to_finding(d))

        header = f"📣 **[任务巡检·公开提醒] {today.isoformat()}**（共 {len(group_findings)} 条）"
        detail_md, mentions = _render_task_blocks(group_findings, include_owner=True)
        message = (header + "\n" + detail_md).strip() if group_findings else ""
        card = None
        if group_findings:
            summary_md = f"**日期**：{today.isoformat()}\n\n**需公开提醒条目**：{len(group_findings)}"
            card = build_patrol_card(
                title="任务巡检提醒（群聊）",
                template="red",
                summary_md=summary_md,
                detail_md=detail_md or "（无）",
            )

        routes["group"] = {
            **group_route,
            "count": len(group_findings),
            "items": [f.to_dict() for f in group_findings],
            "mentions_open_ids": mentions,
            "message": message,
            "card": card,
        }

    # unmapped 路由保持不变
    routes["unmapped"] = unmapped_route

    summary = output.get("summary") or {}
    if isinstance(summary, dict):
        summary["private_count"] = sum(int((bucket or {}).get("count") or 0) for bucket in new_private.values())
        summary["group_count"] = len(new_group_items)
        output["summary"] = summary

    output["routes"] = routes
    output["vacation"] = {
        "date": today.isoformat(),
        "is_holiday": False,
        "personal_checker_enabled": True,
        "skipped": {
            "private_route_keys": [x.get("route_key") for x in skipped_private],
            "group_item_keys": [x.get("key") for x in skipped_group_items],
        },
    }
    return output
