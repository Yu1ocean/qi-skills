#!/usr/bin/env python3
"""Celebrate 阶段正式入口（skill-forge-pipeline）。

修复历史缺陷（V5.17）：旧实现引用了三个根本不存在的 V3 幽灵资产
（card_template_v3.html / assemble_card_v3.py / update_bitable_v3.py），
并在 Bitable 同步失败时打印 "proceeding to ensure workflow continuity" 静默放行。

现在：
  * 只调用真实存在的 V2 脚本 + V3 画廊表；
  * 启动前执行依赖存在性断言（缺任一路径即 raise 熔断）；
  * 任一子步骤失败即 raise，禁止静默降级。

依赖清单（全部相对仓库根目录）：
  user_skills/cyber-inspiration-generator/assets/card_template.html
  user_skills/cyber-inspiration-generator/scripts/assemble_card.py
  user_skills/cyber-inspiration-generator/scripts/capture_screenshot.py
  user_skills/cyber-inspiration-generator/scripts/sync_gallery.py

画廊表（唯一正式表）：
  base PRbvbUyLqaeITqsXNMRcRCM5nhh / table tblHHVXl9ObjSyRw / attachment fldOBqrqET
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

CIG = Path("user_skills/cyber-inspiration-generator")
CARD_TEMPLATE = CIG / "assets" / "card_template.html"
ASSEMBLE_SCRIPT = CIG / "scripts" / "assemble_card.py"
CAPTURE_SCRIPT = CIG / "scripts" / "capture_screenshot.py"
SYNC_GALLERY_SCRIPT = CIG / "scripts" / "sync_gallery.py"

GALLERY_APP_TOKEN = "PRbvbUyLqaeITqsXNMRcRCM5nhh"
GALLERY_TABLE_ID = "tblHHVXl9ObjSyRw"
GALLERY_ATTACHMENT_FIELD_ID = "fldOBqrqET"
LEGACY_GALLERY_TABLE_ID = "tbly6lJBR0QYTBfW"

REQUIRED_DEPENDENCIES = [
    CARD_TEMPLATE,
    ASSEMBLE_SCRIPT,
    CAPTURE_SCRIPT,
    SYNC_GALLERY_SCRIPT,
]


class CelebrateGuardrailViolation(RuntimeError):
    """L3 断言层熔断异常。"""


def assert_dependencies_exist(root: Path) -> None:
    """启动前存在性断言：任一依赖缺失即熔断（禁止引用幽灵 V3 资产）。"""
    missing = [str(p) for p in REQUIRED_DEPENDENCIES if not (root / p).exists()]
    if missing:
        raise CelebrateGuardrailViolation(
            "[L3] Celebrate dependencies missing (refuse to run with ghost assets): "
            + ", ".join(missing)
        )
    print("✅ [L3] dependency existence assertion passed:")
    for p in REQUIRED_DEPENDENCIES:
        print(f"    - {p}")


def assert_official_gallery(table_id: str) -> None:
    if table_id == LEGACY_GALLERY_TABLE_ID:
        raise CelebrateGuardrailViolation(
            f"[L3] refuse legacy inspiration ledger {LEGACY_GALLERY_TABLE_ID}; "
            f"official gallery table is {GALLERY_TABLE_ID}"
        )


def run_or_raise(cmd: list[str], msg: str) -> str:
    print(f"🚀 {msg}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise CelebrateGuardrailViolation(
            f"[L3] {msg} failed (exit {result.returncode}):\n"
            f"STDOUT: {result.stdout.strip()}\nSTDERR: {result.stderr.strip()}"
        )
    print(result.stdout.strip())
    return result.stdout


def celebrate(
    *,
    name: str,
    skill_id: str,
    image_url: str,
    deployed_url: str,
    story: str,
    fact: str,
    card_title: str | None = None,
    skill_type: str = "防错机制",
    status: str = "已上线",
    output_html: str = "index.html",
    screenshot_path: str = "screenshot.png",
    root: Path = Path("."),
    table_id: str = GALLERY_TABLE_ID,
) -> None:
    print(f"🎊 Celebrate stage for skill: {name}")
    assert_dependencies_exist(root)
    assert_official_gallery(table_id)

    subject = card_title or f"技能诞生：{name}"

    # 1. Card assembly (real V2 script + real template)
    run_or_raise([
        "python3", str(root / ASSEMBLE_SCRIPT),
        subject, story, fact, image_url,
        str(root / CARD_TEMPLATE), output_html,
    ], "Assembling cyber card (assemble_card.py + card_template.html)")

    # 2. Full-page screenshot
    run_or_raise([
        "python3", str(root / CAPTURE_SCRIPT),
        "--url", deployed_url, "--output", screenshot_path,
    ], "Capturing full-page screenshot")

    if not Path(screenshot_path).exists():
        raise CelebrateGuardrailViolation(
            f"[L3] screenshot missing after capture: {screenshot_path}"
        )

    # 3. Gallery sync (V3 gallery table, no silent degradation)
    run_or_raise([
        "python3", str(root / SYNC_GALLERY_SCRIPT),
        "--skill-name", subject,
        "--skill-id", skill_id,
        "--skill-type", skill_type,
        "--status", status,
        "--story", story,
        "--fact", fact,
        "--deployed-url", deployed_url,
        "--screenshot", screenshot_path,
        "--app-token", GALLERY_APP_TOKEN,
        "--table-id", table_id,
        "--attachment-field-id", GALLERY_ATTACHMENT_FIELD_ID,
    ], f"Syncing card into V3 gallery {table_id}")

    print("✅ Celebrate stage completed (card + screenshot + gallery record).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--skill-id", required=True)
    parser.add_argument("--image-url", "--image_url", dest="image_url", required=True)
    parser.add_argument("--deployed-url", "--deployed_url", dest="deployed_url", required=True)
    parser.add_argument("--story", required=True)
    parser.add_argument("--fact", required=True)
    parser.add_argument("--card-title", default=None)
    parser.add_argument("--skill-type", default="防错机制")
    parser.add_argument("--status", default="已上线")
    parser.add_argument("--output-html", default="index.html")
    parser.add_argument("--screenshot", default="screenshot.png")
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    celebrate(
        name=args.name,
        skill_id=args.skill_id,
        image_url=args.image_url,
        deployed_url=args.deployed_url,
        story=args.story,
        fact=args.fact,
        card_title=args.card_title,
        skill_type=args.skill_type,
        status=args.status,
        output_html=args.output_html,
        screenshot_path=args.screenshot,
        root=Path(args.root),
    )


if __name__ == "__main__":
    try:
        main()
    except CelebrateGuardrailViolation as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)
