#!/usr/bin/env python3
"""Build a standardized Chinese poster prompt from structured inputs."""
import argparse
import json
import sys
from pathlib import Path

REQUIRED_FIELDS = ["activity_name", "theme", "primary_message"]
ALLOWED_RATIOS = {"9:16", "16:9", "3:4", "4:5", "1:1"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2"}
ALLOWED_TONES = {"premium", "youthful", "global"}
FORBIDDEN_TEXT = ["话术", "TikTok是媒体", "TikTok 是媒体", "亚马逊", "Amazon"]


def validate_payload(payload: dict) -> None:
    missing = [field for field in REQUIRED_FIELDS if not str(payload.get(field, "")).strip()]
    if missing:
        raise ValueError(f"缺少必填字段: {', '.join(missing)}")
    ratio = payload.get("aspect_ratio", "9:16")
    if ratio not in ALLOWED_RATIOS:
        raise ValueError(f"aspect_ratio 仅支持 {sorted(ALLOWED_RATIOS)}，当前为: {ratio}")
    priority = payload.get("scene_priority")
    if priority and priority not in ALLOWED_PRIORITIES:
        raise ValueError(f"scene_priority 仅支持 {sorted(ALLOWED_PRIORITIES)}，当前为: {priority}")
    tone = payload.get("tone_category")
    if tone and tone not in ALLOWED_TONES:
        raise ValueError(f"tone_category 仅支持 {sorted(ALLOWED_TONES)}，当前为: {tone}")
    metrics = payload.get("metrics", [])
    if metrics and not isinstance(metrics, list):
        raise ValueError("metrics 必须是数组，例如 [{\"label\":\"GMV\",\"value\":\"7亿\"}]")
    text_fields = [
        payload.get("activity_name", ""),
        payload.get("theme", ""),
        payload.get("primary_message", ""),
        payload.get("subtitle", ""),
        payload.get("footer", ""),
    ]
    for word in FORBIDDEN_TEXT:
        if any(word in str(text) for text in text_fields if text):
            raise ValueError(f"检测到禁用表达: {word}")


def normalize_list(value):
    if not value:
        return "无"
    if isinstance(value, list):
        return "；".join(str(x) for x in value if str(x).strip()) or "无"
    return str(value)


def build_prompt(payload: dict) -> str:
    style = payload.get("style", "award_premium")
    tone = payload.get("tone_category", "premium")
    priority = payload.get("scene_priority", "P1")
    tone_map = {
        "premium": "高级感，强调商务可信度、质感、秩序感和高规格氛围",
        "youthful": "年轻化，强调活人感、轻盈动势、社媒传播感和更亮的色彩节奏",
        "global": "国际范，强调大留白、全球品牌感、英文友好排版和机场广告式表达",
    }
    style_map = {
        "award_premium": "深色高端颁奖风，黑金/深蓝金配色，金属光效、月桂、奖杯或光环元素，舞台聚光与粒子质感",
        "case_tech": "TikTok Shop 案例集风，紫蓝科技渐变，玻璃拟态卡片，霓虹边框，数据模块清晰",
        "brand_product": "品牌旗舰商品风，产品大图居中，干净高级背景，卖点参数分层呈现，留白充足",
        "clean_light": "浅金/米白干净风，柔和渐变，奖杯或证书主体，商务可信感",
    }
    metric_text = "；".join(
        f"{m.get('label','指标')}：{m.get('value','')}（{m.get('note','')}）" if isinstance(m, dict) else str(m)
        for m in payload.get("metrics", [])
    ) or "无"
    prompt = f"""
生成一张可直接发布的中文商业海报，比例 {payload.get('aspect_ratio', '9:16')}，高清，文字清晰。

【场景优先级】{priority}
【场景类型】{payload.get('scene_type', '未指定，按主题自动判断')}
【主受众】{payload.get('primary_audience', '商家')}
【调性分类】{tone_map.get(tone, tone)}
【海报主题】{payload['theme']}
【活动/项目名称】{payload['activity_name']}
【主标题】{payload['primary_message']}
【副标题/解释】{payload.get('subtitle', '无')}
【品牌/平台 Logo 区】{normalize_list(payload.get('logos'))}
【主体视觉】{payload.get('hero_visual', '根据主题生成品牌商品、奖杯、舞台或案例图主视觉')}
【关键数据】{metric_text}
【底部信息】{payload.get('footer', '保留底部 CTA / 日期 / 扫码区占位，不生成真实二维码')}
【风格】{style_map.get(style, style)}

设计要求：
1. 采用商业海报纵向三段式结构：顶部品牌背书，中部主标题与主视觉，底部数据/策略/CTA。
2. 主标题必须最大且居中或上半区强曝光；副标题不抢主标题。
3. 数据最多 3 组，使用大号数字 + 小号解释，避免信息过载。
4. 使用与调性匹配的配色和字体层级，深色背景时必须保证中文可读。
5. 添加奖杯、光环、几何线条、粒子、玻璃卡片、mockup 场景等元素，但不要遮挡核心文字。
6. 如果出现人脸，仅作为模糊 / 非真实人物处理；不要生成可识别真实人脸。
7. 强化 TikTok Shop 品牌，不要写成“TikTok 媒体资源”或出现竞对品牌名。
8. 招商 / 政策类优先清楚传达价值点和行动入口；战报类优先呈现成绩和方法论；机场 / 全球化场景可增加国际广告屏或城市户外大屏语境。
""".strip()
    return prompt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON payload file path")
    parser.add_argument("--output", required=True, help="Prompt output file path")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    validate_payload(payload)
    prompt = build_prompt(payload)
    Path(args.output).write_text(prompt, encoding="utf-8")
    print(json.dumps({"ok": True, "output": args.output, "aspect_ratio": payload.get("aspect_ratio", "9:16")}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
