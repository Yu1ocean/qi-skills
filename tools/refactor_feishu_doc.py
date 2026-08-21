import json
import os
import re
from pathlib import Path

from byted_aime_sdk import call_aime_tool

DOCUMENT_URL = "https://bytedance.larkoffice.com/docx/Cpf6dwxynol6eixYc9Hcu8TZn1y"
DOWNLOAD_MD = "Claude_Code_与_Vibe-coding_深度分析报告及逐字稿.lark_6.md"
TRANSCRIPT_TXT = "file_transcript_bilingual_full_5.txt"
OUTPUT_MD = "refactor_payload_claude_code_vibe_coding.lark.md"

AUDIO_ZIP = "file_weibo_5286445327845226_audio_3.zip"
WEIBO_URL = "https://video.weibo.com/show?fid=1034:5286442608558180"


def parse_blocks(md_text: str):
    # Returns list in appearance order: [(block_number, block_id)]
    blocks = []
    pattern = re.compile(r"<!--\s*(BLOCK_[0-9]+)\s*\|\s*([a-zA-Z0-9]+)\s*-->")
    for m in pattern.finditer(md_text):
        blocks.append((m.group(1), m.group(2)))
    return blocks


def split_lines(text: str, max_lines: int):
    lines = text.splitlines()
    parts = []
    for i in range(0, len(lines), max_lines):
        parts.append("\n".join(lines[i : i + max_lines]).strip("\n"))
    return parts


def build_segments(transcript_text: str):
    # L1
    l1 = """<grid cols=\"2\">\n<column width=\"65\">\n\n# Claude Code 与 vibe-coding\n\n## 深度消化（L1-L2）+ 带批注的播客字幕档（L3）\n\n- **来源**：Lenny’s Podcast × Boris Cherny（Anthropic，Claude Code 负责人）\n- **音频来源**：微博视频（见附录链接）\n- **整理日期**：2026-05-05\n\n</column>\n<column width=\"35\">\n\n<callout icon=\"bulb\" bgc=\"3\" bc=\"3\">\n\n**一句话摘要**：Claude Code 把编程从“逐行实现”推向“把意图说清楚 → 并行调度多个 agent 执行 → 以验收与安全为硬约束”，软件工程师的角色正在向“builder（构建者）”迁移。\n\n</callout>\n\n</column>\n</grid>\n\n---\n\n## L1｜核心结论 One-Pager\n\n1. **写代码的重心迁移**：从“写对每一行”迁移到“说清楚目标/约束/验收”。\n2. **Agent 的本质是“会行动”**：不只是聊天，而是能使用工具（tool use）并在真实系统中执行。\n3. **多 Agent 并行成为默认形态**：工程师越来越像“调度者 / 编辑部”，同时推进多个任务。\n4. **Plan-Execute 分离是关键护栏**：先出计划、再执行，能显著降低返工与风险。\n5. **角色边界会被重写**：更多人会“能构建软件”；传统岗位标签（包括 software engineer）会被弱化。\n6. **风险不在于 AI 写错一行，而在于验收/治理缺位**：必须制度化测试、review、回滚与安全边界。\n\n## L1｜黑话卡片（术语速查）\n\n| 术语 | 直译 / 解释 | 在本次内容中的含义 |\n|---|---|---|\n| Claude Code | Claude 的代码产品形态 | 以 agent 方式写代码、用工具、开 PR |\n| vibe-coding | 氛围式编程 | 描述意图 + 验收结果，而非逐行手写 |\n| agent | 智能体 | 能用工具并与系统交互的模型实例 |\n| tool use | 工具使用 | 跑命令、读日志、看反馈、提交修复等 |\n| plan mode | 计划模式 | “先不要写代码，先给计划” |\n| auto-accept | 自动接受 | 在计划充分可信时减少人工确认成本 |\n| multi-Clauding | 多开 Claude | 同时跑多个会话 / 多个任务 |\n| builder | 构建者 | 未来更通用的“能把东西做出来的人” |\n| MCP | Model Context Protocol | 让模型更稳定地调用工具与上下文的协议/机制 |\n"""

    # L2
    l2 = f"""## L2｜背景\n\n- 这是一次围绕 **Claude Code** 的访谈，对话嘉宾为 Anthropic 的 Claude Code 负责人 Boris Cherny。\n- 对话核心不是“某个提示词技巧”，而是：\n  - **软件如何被生产**（工作流）\n  - **人类角色如何变化**（组织与岗位）\n  - **安全与治理如何跟上**（验收与边界）\n\n## L2｜按主题切分的深度分析\n\n### 主题 1：vibe-coding 的实质——“表达意图 + 校验结果”\n\n- 这里的“氛围”并不是随意，而是把人的精力从实现细节转向：\n  - 目标与约束定义\n  - 风险边界与回滚\n  - 验收与质量把关\n\n### 主题 2：Agent 化——从“会写代码”到“会用工具做事”\n\n- 当模型开始能用工具（tools）并在系统里行动时，它更像一个“同事”。\n- 这会把影响从工程岗位外溢到更多电脑工作：PM、运营、设计、数据等。\n\n### 主题 3：工作流的关键护栏——Plan-Execute 分离\n\n- **80% 的任务从 plan mode 开始**的要点是：\n  1) 先得到可审查的计划（Plan）\n  2) 人先审计划（Review：边界/风险/验收）\n  3) 再执行（Execute）\n- 这比“多写几句 prompt”更重要，因为它可复用、可规模化。\n\n### 主题 4：岗位与组织的改写——从 software engineer 到 builder\n\n- 对话里反复出现的判断：\n  - “每个人都会变成产品经理，每个人都会写（或生成）代码”\n  - 传统岗位标签会被更通用的“builder”取代\n- 这里的关键，不是每个人都会写某门语言，而是：\n  - 每个人都能用工具链把东西做出来\n  - 组织需要新的验收、权限与安全体系\n\n### 主题 5：必须直面的风险（不是可选项）\n\n- **技能退化焦虑**：个人可不焦虑，但团队必须用制度兜底。\n- **auto-accept 的前提**：计划与验收足够强，否则只是把风险后移。\n- **安全与权限**：模型越会“行动”，越需要明确的权限、审计与回滚。\n\n---\n\n"""

    # L3 intro
    l3_intro = """## L3｜带批注的播客字幕档（英文原文 + 中文翻译）\n\n<callout icon=\"bulb\" bgc=\"2\" bc=\"2\">\n\n- 本节为 **完整逐字稿**（英文原文 + 中文翻译），为保证 **100% 不遗漏**，不做摘要与删改。\n- 为便于检索，转写结果按 chunk 分段；你可以按时间段快速定位。\n- 如需回听原音频，对照附录的音频 ZIP。\n\n</callout>\n\n"""

    # L3 full transcript (verbatim)
    transcript_parts = split_lines(transcript_text.strip("\n"), max_lines=120)

    # L4 appendix
    l4 = f"""\n\n---\n\n## L4｜附录：资产归档\n\n- **飞书妙记（Minutes）链接**：⚠️[数据断链_待自愈｜当前工具链缺少“上传音频到妙记”的可用命令；需要人工上传后我再补链]\n- **原始微博视频链接**：{WEIBO_URL}\n- **抓取声明**：音频与逐字稿仅用于内部学习与研究；若涉及对外传播请自行确认合规边界。\n\n### 原始音频 ZIP（解压后为 MP3）\n\n![文件]({AUDIO_ZIP})\n\n### 逐字稿原始文件（备份）\n\n![文件]({TRANSCRIPT_TXT})\n"""

    segments = [l1.strip("\n"), l2.strip("\n"), l3_intro.strip("\n")] + transcript_parts + [l4.strip("\n")]
    return segments


def main():
    root = Path(__file__).resolve().parents[1]

    download_md_path = root / DOWNLOAD_MD
    transcript_path = root / TRANSCRIPT_TXT
    output_md_path = root / OUTPUT_MD

    if not download_md_path.exists():
        raise FileNotFoundError(download_md_path)
    if not transcript_path.exists():
        raise FileNotFoundError(transcript_path)

    download_md_text = download_md_path.read_text(encoding="utf-8")
    transcript_text = transcript_path.read_text(encoding="utf-8")

    blocks = parse_blocks(download_md_text)
    if not blocks:
        raise RuntimeError("No blocks found in downloaded markdown")

    segments = build_segments(transcript_text)

    # Use the first N blocks in appearance order to host our segments.
    if len(blocks) < len(segments):
        raise RuntimeError(f"Not enough blocks to place content: blocks={len(blocks)} segments={len(segments)}")

    # Write a preview markdown (optional but helps for media path resolution)
    output_md_path.write_text("\n\n".join(segments) + "\n", encoding="utf-8")

    modifications = []
    for idx, (block_number, block_id) in enumerate(blocks):
        if idx < len(segments):
            content = segments[idx]
            modifications.append(
                {
                    "block_id": block_id,
                    "block_number": block_number,
                    "content": content,
                    "modification_type": "update",
                }
            )
        else:
            # Delete all remaining old blocks
            modifications.append(
                {
                    "block_id": block_id,
                    "block_number": block_number,
                    "content": "",
                    "modification_type": "update",
                }
            )

    payload = {
        "document_url": DOCUMENT_URL,
        "markdown_file_path": str(output_md_path),
        "modifications": modifications,
    }

    print(f"Generated markdown: {output_md_path}")

    # Execute update via AIME tool call directly (avoid argv length limit)
    result = call_aime_tool(
        toolset="lark",
        tool_name="mcp:lark_update_lark_doc",
        parameters=payload,
        response_format="text",
    )
    print(result)


if __name__ == "__main__":
    main()
