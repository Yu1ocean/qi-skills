#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1.3 结构护栏回归测试（GUARD-POST-001~005）。

沙盒隔离铁律：本测试只做本地校验 / preflight 级验证，绝不触发真实发信。
payload 落在 `.ephemeral_pool/`，遵守 `[TASK_ID]_[TOPIC_SLUG].*.json` 命名规范。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _payload_guard import (  # noqa: E402
    EPHEMERAL_DIR,
    PayloadGuardError,
    assert_post_content_shape,
    looks_like_post_payload,
    summarize_payload,
)

TASK_ID = "guardtest13"
TOPIC = "统一发射器结构护栏回归"
TOPIC_SLUG = "post_guard"
FAILURES: list[str] = []
PASSED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSED
    if ok:
        PASSED += 1
        print(f"[PASS] {name} {detail}")
    else:
        FAILURES.append(f"{name} {detail}")
        print(f"[FAIL] {name} {detail}")


def good_block(title: str = "结构护栏回归") -> dict:
    return {"title": title, "content": [[{"tag": "text", "text": "统一发射器结构护栏回归验证"}]]}


def expect_reject(name: str, payload, code: str) -> None:
    try:
        assert_post_content_shape(payload)
    except PayloadGuardError as exc:
        check(name, code in str(exc), f"-> {str(exc)[:90]}")
        return
    check(name, False, "-> 未被拦截（危险）")


def expect_pass(name: str, payload) -> None:
    try:
        result = assert_post_content_shape(payload)
        check(name, result in {"ok", "legacy_bridge"}, f"-> {result}")
    except PayloadGuardError as exc:
        check(name, False, f"-> 误拦截: {exc}")


def run_intercept_cases() -> None:
    print("\n=== A. 8 条拦截 case ===")
    # 事故原貌：content 顶层元数据与语种键并列
    expect_reject(
        "A1 事故原貌 content 顶层 task_id/topic 与 zh_cn 并列",
        {"msg_type": "post", "content": {"task_id": "t1", "topic": "x", "zh_cn": good_block()}},
        "GUARD-POST-002",
    )
    expect_reject(
        "A2 content 顶层 run_id 污染",
        {"content": {"run_id": "r1", "zh_cn": good_block()}},
        "GUARD-POST-002",
    )
    expect_reject(
        "A3 payload 本体顶层语种键旁挂 task_id",
        {"zh_cn": good_block(), "task_id": "t1"},
        "GUARD-POST-002",
    )
    expect_reject("A4 缺少 content", {"msg_type": "post", "title": "只有标题"}, "GUARD-POST-001")
    expect_reject("A5 content 为字符串", {"msg_type": "post", "content": "纯文本"}, "GUARD-POST-001")
    expect_reject("A6 content 顶层为空", {"msg_type": "post", "content": {}}, "GUARD-POST-003")
    expect_reject(
        "A7 语种块 content 非 list-of-list",
        {"content": {"zh_cn": {"title": "t", "content": "纯文本"}}},
        "GUARD-POST-004",
    )
    expect_reject(
        "A8 段落元素缺少 tag",
        {"content": {"zh_cn": {"title": "t", "content": [[{"text": "无 tag"}]]}}},
        "GUARD-POST-005",
    )


def run_regression_cases() -> None:
    print("\n=== B. 6 条回归 case（正常结构必须通过）===")
    expect_pass("B1 单语种带 title", {"msg_type": "post", "content": {"zh_cn": good_block()}})
    expect_pass("B2 单语种不带 title", {"content": {"zh_cn": {"content": [[{"tag": "text", "text": "a"}]]}}})
    expect_pass(
        "B3 多语种 zh_cn + en_us + ja_jp",
        {
            "content": {
                "zh_cn": good_block(),
                "en_us": {"title": "Guard", "content": [[{"tag": "text", "text": "ok"}]]},
                "ja_jp": {"content": [[{"tag": "text", "text": "ok"}]]},
            }
        },
    )
    expect_pass(
        "B4 多段落 + 多元素（含 a 标签）",
        {
            "content": {
                "zh_cn": {
                    "title": "多段",
                    "content": [
                        [{"tag": "text", "text": "第一段"}],
                        [{"tag": "text", "text": "链接："}, {"tag": "a", "text": "点我", "href": "https://example.com"}],
                    ],
                }
            }
        },
    )
    expect_pass("B5 payload 本体即 content（顶层语种键，无元数据）", {"zh_cn": good_block()})
    expect_pass(
        "B6 v1.2 旧版差旅大盘兼容桥 payload 豁免",
        {"msg_type": "post", "title": "差旅大盘", "summary": "摘要", "content": "正文 https://x"},
    )


def run_other_msg_type_regression() -> None:
    print("\n=== C. interactive / text 路径零影响回归 ===")
    card_payload = {
        "schema": "2.0",
        "task_id": TASK_ID,
        "header": {"title": {"tag": "plain_text", "content": "卡片"}},
        "body": {"elements": [{"tag": "markdown", "content": "统一发射器结构护栏回归"}]},
    }
    text_payload = {"text": "统一发射器结构护栏回归：纯文本消息"}
    check("C1 card payload 不被识别为 post", not looks_like_post_payload(card_payload, filename="a.card.json"))
    check("C2 text payload 不被识别为 post", not looks_like_post_payload(text_payload, filename="a.payload.json"))
    check("C3 post payload 能被识别", looks_like_post_payload({"content": {"zh_cn": good_block()}}, filename="a.json"))
    # 根因修复回归：元数据不得再被当成主题素材
    polluted = {"task_id": "统一发射器结构护栏回归", "content": {"zh_cn": {"content": [[{"tag": "text", "text": "x"}]]}}}
    check("C4 task_id 已从主题素材白名单移除", "统一发射器结构护栏回归" not in summarize_payload(polluted))


def run_preflight_cases() -> None:
    print("\n=== D. preflight 端到端（本地校验，不发信）===")
    EPHEMERAL_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, AIME_TASK_ID=TASK_ID, AIME_TASK_TITLE=TOPIC, AIME_CALLER_ROLE="main")

    def preflight(payload: dict, suffix: str) -> subprocess.CompletedProcess:
        path = EPHEMERAL_DIR / f"[{TASK_ID}]_{TOPIC_SLUG}{suffix}"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "centralized_transmitter.py"),
                "preflight",
                str(path),
                f"--task-id={TASK_ID}",
                f"--topic={TOPIC}",
                "--caller-role=main",
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(SCRIPT_DIR),
        )

    bad = preflight(
        {"msg_type": "post", "task_id": TASK_ID, "content": {"task_id": TASK_ID, "topic": TOPIC, "zh_cn": good_block(TOPIC)}},
        ".post.json",
    )
    check(
        "D1 preflight 拦截顶层污染 post",
        bad.returncode != 0 and "GUARD-POST-002" in (bad.stdout + bad.stderr),
        f"-> rc={bad.returncode}",
    )
    good = preflight({"msg_type": "post", "task_id": TASK_ID, "content": {"zh_cn": good_block(TOPIC)}}, ".post.json")
    check("D2 preflight 放行合法 post", good.returncode == 0, f"-> rc={good.returncode} {good.stdout[-80:].strip()}")
    card = preflight(
        {
            "schema": "2.0",
            "task_id": TASK_ID,
            "header": {"title": {"tag": "plain_text", "content": TOPIC}},
            "body": {"elements": [{"tag": "markdown", "content": TOPIC}]},
        },
        ".card.json",
    )
    check("D3 preflight 卡片路径零影响", card.returncode == 0, f"-> rc={card.returncode}")


def main() -> int:
    run_intercept_cases()
    run_regression_cases()
    run_other_msg_type_regression()
    run_preflight_cases()
    total = PASSED + len(FAILURES)
    print(f"\n=== 汇总：{PASSED}/{total} 通过 ===")
    if FAILURES:
        for item in FAILURES:
            print(f"  FAILED: {item}")
        return 1
    print("ALL GREEN: 8 拦截 + 6 回归 + interactive/text 零影响 + preflight 端到端 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
