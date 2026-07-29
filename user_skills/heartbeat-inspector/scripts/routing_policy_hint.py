#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

DEFAULT_ROUTE = "L0_FLAT"
DEFAULT_REASON = "heartbeat-inspector 只负责产出结构化事件；正式发送前必须先经过 route_manifest.yaml / _routing_engine.py 判定。"
THREAD_WHITELIST = {
    ("taskflow_ack", "ack"): "TaskFlow 入库确认是 manifest 白名单场景，可保留 L1_THREAD_REPLY。",
}


def decide_route(event_type: str, scene: str) -> dict:
    event = (event_type or "").strip()
    current_scene = (scene or "").strip()
    if (current_scene, event) in THREAD_WHITELIST:
        return {
            "scene": current_scene,
            "event_type": event,
            "recommended_route": "L1_THREAD_REPLY",
            "allow_thread_reply": True,
            "reason": THREAD_WHITELIST[(current_scene, event)],
        }
    return {
        "scene": current_scene,
        "event_type": event,
        "recommended_route": DEFAULT_ROUTE,
        "allow_thread_reply": False,
        "reason": DEFAULT_REASON,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit heartbeat-inspector routing hints for rehearsal and local validation.")
    parser.add_argument("--event-type", required=True, help="Structured event type, e.g. chat_task / mention_message_new / ack")
    parser.add_argument("--scene", default="default", help="Routing scene name, e.g. default / taskflow_ack")
    args = parser.parse_args()
    print(json.dumps(decide_route(args.event_type, args.scene), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
