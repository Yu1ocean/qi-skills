#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_DASHBOARD_URL = "https://216a3e1709fd.aime-app.bytedance.net/"
DEFAULT_CHAT_REGISTRY_USAGE = "travel_dashboard_report"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def count_daily_new_alerts(payload: dict[str, Any]) -> int:
    summary_value = (payload.get("summary") or {}).get("daily_new_alerts")
    if isinstance(summary_value, int):
        return summary_value
    daily = (payload.get("compliance") or {}).get("daily_new_alerts")
    if isinstance(daily, dict):
        count = daily.get("count")
        if isinstance(count, int):
            return count
        alerts = daily.get("alerts")
        if isinstance(alerts, list):
            return len(alerts)
    if isinstance(daily, list):
        return len(daily)
    return 0


def collect_daily_new_alerts(payload: dict[str, Any], *, limit: int = 5) -> tuple[list[dict[str, str]], int]:
    daily = (payload.get("compliance") or {}).get("daily_new_alerts")
    alerts: list[Any] = []
    if isinstance(daily, dict):
        raw_alerts = daily.get("alerts")
        if isinstance(raw_alerts, list):
            alerts = raw_alerts
    rows: list[dict[str, str]] = []
    for item in alerts[:limit]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "person": str(item.get("person") or "--"),
                "rule_type": str(item.get("rule_type") or "--"),
                "route": str(item.get("route") or "--"),
                "date_range": str(item.get("date_range") or item.get("date") or "--"),
            }
        )
    remaining = max(len(alerts) - len(rows), 0)
    return rows, remaining


def normalize_text_for_match(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"\\s+", "", text)
    return text.replace("—", "-").replace("–", "-").replace("至", "~")


def iter_daily_new_alerts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    daily = (payload.get("compliance") or {}).get("daily_new_alerts")
    if isinstance(daily, dict) and isinstance(daily.get("alerts"), list):
        return [item for item in daily["alerts"] if isinstance(item, dict)]
    return []


def validate_daily_new_alerts_in_deploy_html(payload: dict[str, Any], deploy_html: Path) -> None:
    if not deploy_html.exists():
        raise FileNotFoundError(f"deploy HTML not found: {deploy_html}")
    html_text = normalize_text_for_match(deploy_html.read_text(encoding="utf-8"))
    for alert in iter_daily_new_alerts(payload):
        person = str(alert.get("person") or "--")
        date_range = str(alert.get("date_range") or alert.get("date") or "--")
        trip_type = str(alert.get("rule_type") or alert.get("trip_type") or alert.get("type") or "--")
        required_tokens = [person, date_range, trip_type]
        if not all(normalize_text_for_match(token) in html_text for token in required_tokens):
            raise ValueError(f"[ALERT_MISMATCH] card alert not found in deploy HTML: {person} {date_range}")


def build_daily_new_alert_elements(
    payload: dict[str, Any],
    *,
    limit: int = 5,
    new_label_style: str = "tag",
) -> list[dict[str, Any]]:
    daily = (payload.get("compliance") or {}).get("daily_new_alerts")
    rows, remaining = collect_daily_new_alerts(payload, limit=limit)
    if not rows:
        message = daily.get("message") if isinstance(daily, dict) else "今日无新增预警 ✅"
        return [{"tag": "markdown", "content": str(message or "今日无新增预警 ✅")}]

    if new_label_style not in {"tag", "lark_md"}:
        raise ValueError(f"unsupported new_label_style: {new_label_style}")

    elements: list[dict[str, Any]] = []
    for row in rows:
        alert_text = f"**{row['person']} · {row['rule_type']}**｜{row['route']}｜{row['date_range']}"
        if new_label_style == "lark_md":
            elements.append({"tag": "markdown", "content": f"**🆕 NEW** {alert_text}"})
            continue
        elements.append(
            {
                "tag": "column_set",
                "columns": [
                    {
                        "tag": "column",
                        "width": "shrink",
                        "elements": [
                            {
                                "tag": "tag",
                                "text": {"tag": "plain_text", "content": "NEW"},
                                "color": "red",
                            }
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [
                            {
                                "tag": "markdown",
                                "content": alert_text,
                            }
                        ],
                    },
                ],
            }
        )
    if remaining > 0:
        elements.append({"tag": "markdown", "content": f"另有 **{remaining}** 条新增预警，请打开大屏查看"})
    return elements


def render_template(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, replacement in replacements.items():
            value = value.replace("{{" + key + "}}", replacement)
        return value
    if isinstance(value, list):
        return [render_template(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, replacements) for key, item in value.items()}
    return value


def build_card(
    snapshot: dict[str, Any],
    template: dict[str, Any],
    *,
    task_id: str,
    topic: str,
    dashboard_url: str,
    chat_registry_usage: str,
    new_label_style: str = "tag",
) -> dict[str, Any]:
    summary = snapshot.get("summary") or {}
    compliance = snapshot.get("compliance") or {}
    total_trips = summary.get("total_trips", 0)
    compliance_alerts = summary.get("compliance_alerts")
    if not isinstance(compliance_alerts, int):
        alerts = compliance.get("alerts")
        compliance_alerts = len(alerts) if isinstance(alerts, list) else int(compliance.get("alert_count") or 0)
    daily_new_alerts = count_daily_new_alerts(snapshot)
    replacements = {
        "TOTAL_TRIPS": str(total_trips),
        "COMPLIANCE_ALERTS": str(compliance_alerts),
        "DAILY_NEW_ALERTS": str(daily_new_alerts),
        "DASHBOARD_URL": dashboard_url,
    }
    card = render_template(template, replacements)
    alert_elements = build_daily_new_alert_elements(snapshot, new_label_style=new_label_style)
    body = card.get("body") or {}
    elements = body.get("elements") if isinstance(body, dict) else None
    if not isinstance(elements, list):
        raise ValueError("schema 2.0 card must use body.elements")
    if len(elements) < 2:
        raise ValueError("card template must contain summary and button elements")
    body["elements"] = [elements[0], *alert_elements, *elements[1:]]
    card["schema"] = "2.0"
    card["task_id"] = task_id
    card["topic"] = topic
    card["chat_registry_usage"] = chat_registry_usage
    return card


def validate_card(card: dict[str, Any]) -> None:
    if card.get("schema") != "2.0":
        raise ValueError("card schema must be 2.0")
    if not isinstance(card.get("body"), dict) or not isinstance(card["body"].get("elements"), list):
        raise ValueError("schema 2.0 card must use body.elements")
    if "elements" in card:
        raise ValueError("legacy V1 top-level elements is not allowed")
    text = json.dumps(card, ensure_ascii=False)
    for required in ("行程", "合规预警", "今日新增预警", "团队差旅大屏"):
        if required not in text:
            raise ValueError(f"missing required content: {required}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Feishu card schema 2.0 payload for team travel dashboard")
    parser.add_argument("--snapshot", default="output/snapshots/2026-07-27.json")
    parser.add_argument("--template", default="assets/team_travel_dashboard_card_template.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--topic", default="团队差旅大屏自动更新")
    parser.add_argument("--dashboard-url", default=DEFAULT_DASHBOARD_URL)
    parser.add_argument("--chat-registry-usage", default=DEFAULT_CHAT_REGISTRY_USAGE)
    parser.add_argument("--new-label-style", choices=("tag", "lark_md"), default="tag", help="NEW label renderer: native tag first, lark_md fallback when card service rejects tag component")
    parser.add_argument("--deploy-html", default="output/travel_dashboard.html", help="HTML file that will be deployed to the production dashboard; daily_new_alerts must be traceable in this file before card payload generation")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parents[1]
    snapshot = load_json((skill_root / args.snapshot).resolve())
    deploy_html = (skill_root / args.deploy_html).resolve()
    validate_daily_new_alerts_in_deploy_html(snapshot, deploy_html)
    template = load_json((skill_root / args.template).resolve())
    card = build_card(
        snapshot,
        template,
        task_id=args.task_id,
        topic=args.topic,
        dashboard_url=args.dashboard_url,
        chat_registry_usage=args.chat_registry_usage,
        new_label_style=args.new_label_style,
    )
    validate_card(card)

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "schema": card.get("schema"), "task_id": args.task_id, "topic": args.topic, "chat_registry_usage": args.chat_registry_usage}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
