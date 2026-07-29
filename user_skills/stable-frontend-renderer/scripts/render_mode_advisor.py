#!/usr/bin/env python3
import argparse
import json

DEFAULT_INTERACTION_LEVELS = {"display", "light", "medium", "heavy"}


def validate_inputs(interaction: str):
    assert interaction is not None
    if interaction not in DEFAULT_INTERACTION_LEVELS:
        raise ValueError(f"Unsupported interaction level: {interaction}")


def decide_mode(interaction: str, chat_scene: bool, existing_h5: bool, needs_runtime: bool, third_party: bool):
    if existing_h5:
        return {
            "recommended_mode": "controlled_h5_preview",
            "stability": "medium",
            "should_be_default_in_chat": False,
            "reason": "已有完整 H5 页面时，应按受控 iframe / 同域代理思路处理，而不是误塞进聊天动态卡片主链路。",
            "fallbacks": ["static_snapshot", "doc_embed", "external_full_page"],
        }

    if interaction == "display":
        return {
            "recommended_mode": "static_display",
            "stability": "very_high",
            "should_be_default_in_chat": True,
            "reason": "纯展示需求优先用静态展示、文档嵌入、SVG 或受控 HTML，不必引入运行时。",
            "fallbacks": ["svg_or_whiteboard", "lark_doc_embed", "static_html"],
        }

    if interaction == "light":
        return {
            "recommended_mode": "aui_quick_preview",
            "stability": "high",
            "should_be_default_in_chat": True,
            "reason": "轻交互应优先收敛到 AUI 官方组件与快速预览链路。",
            "fallbacks": ["aui_light_card", "static_summary_with_actions"],
        }

    if interaction == "medium" and not third_party and not needs_runtime:
        return {
            "recommended_mode": "aui_quick_preview",
            "stability": "medium_high",
            "should_be_default_in_chat": True,
            "reason": "中等交互在不引入第三方依赖和重运行时的前提下，仍可尽量留在 AUI 快速预览链路。",
            "fallbacks": ["aui_light_card", "static_summary_with_actions"],
        }

    return {
        "recommended_mode": "runtime_dynamic_preview",
        "stability": "medium",
        "should_be_default_in_chat": False,
        "reason": "需求已进入强交互或运行时模式，应显式接受更高风险，并提供降级路径。",
        "fallbacks": ["static_snapshot", "doc_embed", "external_full_page"],
    }


def main():
    parser = argparse.ArgumentParser(description="Recommend a stable frontend preview mode.")
    parser.add_argument("--interaction", choices=["display", "light", "medium", "heavy"], required=True)
    parser.add_argument("--chat-scene", action="store_true", help="Whether the target scene is in-chat preview")
    parser.add_argument("--existing-h5", action="store_true", help="Whether there is an existing H5 page to reuse")
    parser.add_argument("--needs-runtime", action="store_true", help="Whether the solution requires heavy runtime execution")
    parser.add_argument("--third-party", action="store_true", help="Whether third-party dependencies/materials are required")
    args = parser.parse_args()

    validate_inputs(args.interaction)

    result = decide_mode(
        interaction=args.interaction,
        chat_scene=args.chat_scene,
        existing_h5=args.existing_h5,
        needs_runtime=args.needs_runtime,
        third_party=args.third_party,
    )
    result["chat_scene"] = args.chat_scene
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
