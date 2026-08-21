#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multiselect_write_guard.py — 飞书表格多选单元格写入前置断言（L3 运行时熔断）

对应 SKILL.md v7.5 陷阱6：
  飞书多选（Multi-Select）单元格的值是「选项对象数组」，不是字符串。
  逗号串（如 "EU,UK,JP"）会被引擎当作一个整体文本去匹配选项列表，
  多值时必然匹配失败 -> 药丸(Pill)不渲染 + 右上角红色校验失败角标。
  单值（如 "EU"）恰好命中选项时不报错，会造成「偶发正常」的假象。

断言项:
  1. [TRAP6-A] value 字段承载含分隔符（, ， ; / |）的字符串 -> 逗号串污染，熔断
  2. [TRAP6-B] 声明多选写入但 multiple_values 缺失或结构不是 [{"value": ...}, ...] -> 熔断
  3. [TRAP6-C] 提供 --allowed-options 时，任一 value 不在选项白名单内 -> 熔断

用法:
  # A. 由标签列表生成并校验（推荐，通过后直接打印可复制的 cells payload）
  python3 scripts/multiselect_write_guard.py \
    --values "EU,UK,JP" [--field multiple_values] [--allowed-options "EU,UK,JP,US,SEA"]

  # B. 体检既有 cells payload
  python3 scripts/multiselect_write_guard.py \
    --cells-json '[[{"multiple_values":[{"value":"EU"},{"value":"UK"}]}]]'

退出码:
  0 = PASSED，允许继续调用 `lark-cli sheets +cells-set` 写入
  1 = FAILED（护栏熔断），禁止调用方兜底继续写入
  2 = 用法错误（参数缺失 / JSON 无法解析）
"""
from __future__ import annotations

import argparse
import json
import sys

# 多选标签内不应出现的分隔符：出现即说明调用方在用「一个字符串塞多个标签」
SEPARATORS = (",", "，", ";", "；", "/", "|", "、")


class MultiSelectGuardError(RuntimeError):
    """多选写入护栏熔断异常。"""


def _looks_like_joined_string(text: str) -> str | None:
    """返回命中的分隔符；未命中返回 None。"""
    for sep in SEPARATORS:
        if sep in text:
            return sep
    return None


def validate_write_field(field: str) -> None:
    """陷阱6：只允许 multiple_values 字段写多选单元格。"""
    if field.strip().lower() != "multiple_values":
        raise MultiSelectGuardError(
            f"[TRAP6-B] 多选单元格必须以 multiple_values 字段写入，当前 field={field!r}。"
            " 禁止使用 value 纯文本或 +csv-put，否则药丸不渲染并触发红色校验失败角标。"
        )


def validate_no_joined_value(cell: dict) -> None:
    """陷阱6-A：value 字段承载逗号串 = 典型污染写法。"""
    raw = cell.get("value")
    if not isinstance(raw, str):
        return
    sep = _looks_like_joined_string(raw)
    if sep:
        raise MultiSelectGuardError(
            f"[TRAP6-A] 检测到逗号串污染：value={raw!r} 含分隔符 {sep!r}。"
            " 飞书多选值是选项数组，整串会被当成一个不存在的选项去匹配 -> 校验必然失败。"
            ' 请改用 multiple_values 结构化数组，如 {"multiple_values":[{"value":"EU"},{"value":"UK"}]}。'
        )


def normalize_multiple_values(cell: dict) -> list[str]:
    """陷阱6-B：校验 multiple_values 结构，返回标签列表。"""
    if "multiple_values" not in cell:
        raise MultiSelectGuardError(
            f"[TRAP6-B] 多选写入缺失 multiple_values 字段，当前 cell={cell!r}。"
            " 禁止用 value 纯文本冒充多选值。"
        )
    mv = cell["multiple_values"]
    if not isinstance(mv, list) or not mv:
        raise MultiSelectGuardError(
            f"[TRAP6-B] multiple_values 必须是非空数组，当前: {mv!r}。"
        )
    labels: list[str] = []
    for idx, item in enumerate(mv):
        if not isinstance(item, dict) or "value" not in item:
            raise MultiSelectGuardError(
                f"[TRAP6-B] multiple_values[{idx}] 结构非法: {item!r}。"
                ' 必须是 [{"value": "EU"}, {"value": "UK"}] 形态。'
            )
        label = item["value"]
        if not isinstance(label, str) or not label.strip():
            raise MultiSelectGuardError(
                f"[TRAP6-B] multiple_values[{idx}].value 必须是非空字符串，当前: {label!r}。"
            )
        sep = _looks_like_joined_string(label)
        if sep:
            raise MultiSelectGuardError(
                f"[TRAP6-A] multiple_values[{idx}].value={label!r} 仍含分隔符 {sep!r}，"
                " 说明逗号串只是被搬进了数组里。每个标签必须单独成为一个元素。"
            )
        labels.append(label.strip())
    return labels


def validate_allowed_options(labels: list[str], allowed: list[str]) -> None:
    """陷阱6-C：标签必须命中选项白名单。"""
    if not allowed:
        return
    whitelist = {a.strip() for a in allowed if a.strip()}
    illegal = [x for x in labels if x not in whitelist]
    if illegal:
        raise MultiSelectGuardError(
            f"[TRAP6-C] 标签 {illegal} 不在多选选项列表 {sorted(whitelist)} 中。"
            " 不在选项列表内的值会被判定为校验失败，请先确认列的选项配置。"
        )


def assert_multiselect_write_safe(
    cells: list[list[dict]],
    allowed_options: list[str] | None = None,
    field: str = "multiple_values",
) -> dict:
    """对整个 cells payload 执行三项断言，任一违规即 raise。"""
    validate_write_field(field)
    if not cells or not isinstance(cells, list):
        raise MultiSelectGuardError(f"[GUARD] cells payload 必须是非空二维数组，当前: {cells!r}")

    all_labels: list[list[str]] = []
    for r, row in enumerate(cells):
        if not isinstance(row, list):
            raise MultiSelectGuardError(f"[GUARD] cells[{r}] 必须是数组，当前: {row!r}")
        for c, cell in enumerate(row):
            if not isinstance(cell, dict):
                raise MultiSelectGuardError(f"[GUARD] cells[{r}][{c}] 必须是对象，当前: {cell!r}")
            validate_no_joined_value(cell)
            labels = normalize_multiple_values(cell)
            validate_allowed_options(labels, allowed_options or [])
            all_labels.append(labels)

    normalized = [
        [{"multiple_values": [{"value": v} for v in labels]}]
        for labels in all_labels
    ]
    flat = [c[0] for c in normalized]
    return {
        "status": "ok",
        "field": field,
        "labels": all_labels,
        "expected_lengths": [len(x) for x in all_labels],
        "cells_payload": json.dumps([flat], ensure_ascii=False),
    }


def _split(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="飞书多选单元格写入前置断言（陷阱6）")
    ap.add_argument("--values", default="", help="逗号分隔的多选标签，如 'EU,UK,JP'")
    ap.add_argument("--cells-json", default="", help="原始 cells payload（二维数组 JSON）")
    ap.add_argument("--field", default="multiple_values", help="写入字段，必须为 multiple_values")
    ap.add_argument("--allowed-options", default="", help="逗号分隔的合法选项白名单")
    args = ap.parse_args()

    if not args.values and not args.cells_json:
        print("USAGE ERROR: 必须提供 --values 或 --cells-json 之一", file=sys.stderr)
        return 2

    if args.cells_json:
        try:
            cells = json.loads(args.cells_json)
        except json.JSONDecodeError as exc:
            print(f"USAGE ERROR: --cells-json 无法解析为 JSON: {exc}", file=sys.stderr)
            return 2
    else:
        cells = [[{"multiple_values": [{"value": v} for v in _split(args.values)]}]]

    try:
        result = assert_multiselect_write_safe(cells, _split(args.allowed_options), args.field)
    except MultiSelectGuardError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"PASSED: labels={result['labels']} expected_lengths={result['expected_lengths']}")
    print(f"cells payload -> --cells '{result['cells_payload']}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
