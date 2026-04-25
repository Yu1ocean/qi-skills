---
name: skill-forge-pipeline-v4
description: 自动化技能创建、升级、打包发布与归档流水线，强制执行 Forge、Celebrate、Archive 闭环，并自动发布技能 zip 到飞书云盘、回挂说明文档。适用于新建技能、升级现有技能、需要同步说明文档附件与归档台账的场景。
---
# 技能锻造流水线 (Forge Pipeline V5)

本技能负责 Aime 系统中技能的创建、修改与自动化部署。它通过集成 `aime-skill-creator`、`cyber-inspiration-generator`、`omni-asset-archiver` 与飞书高权限挂载链路，确保每一个技能的生命周期都得到完整记录。

## 适用场景
- **技能创建与重构**：从零构建或升级现有技能。
- **技能资产回挂**：需要把最新技能目录压缩包自动上传到飞书云盘，并挂载回对应说明文档。

## 强制原子工作流 (Atomic Transaction Workflow)

必须在一次子任务执行中**闭环且强制**地完成以下三个步骤。严禁在完成第一步后等待用户确认或跳过后续步骤。

### 1. Forge 锻造（核心逻辑编写）
作为顶层代理，直接向下调起内置技能 `inner_skills/aime-skill-creator`。
- **执行目标**：按照 `aime-skill-creator` 的 SOP 完成核心 `SKILL.md` 编写、目录初始化、验证及打包（Pack）。
- **必须产出**：技能名称、描述、包 ID、目标技能目录路径。

### 2. Celebrate 庆祝（V3 赛博灵感）
只要技能打包成功，必须**无缝且强制**调起 `cyber-inspiration-generator` (V3)。
- **视觉生成**：调用 `image-generate` 生成一张 16:9 的赛博朋克风 AI 视觉图。
- **灵感铸造**：生成 V3 版本的赛博朋克风灵感卡片，文案需采用 Aime 护主小精灵视角的双轨剧本（小说+说明）。
- **画廊同步**：强制将卡片元数据、截图及文案附加到 V3 画廊多维表格：`https://bytedance.larkoffice.com/base/PRbvbUyLqaeITqsXNMRcRCM5nhh?table=tblHHVXl9ObjSyRw`。

### 3. Archive 入库（图书馆台账 + Zip 资产发布）
到了“入库”环节，流水线**严禁直接操作飞书表格**，但必须先完成技能压缩包发布与文档挂载。
- **Zip 打包**：在最后阶段强制运行 `scripts/register_skill.py`，传入 `--skill-dir`，将目标技能目录（如 `user_skills/xxx/`）打包为同级 `.zip` 文件。
- **云盘发布**：`scripts/register_skill.py` 必须将 `.zip` 上传到飞书云盘，并强制为 `yuqinan@bytedance.com` 赋予 `full_access` 权限。
- **文档挂载**：`scripts/register_skill.py` 必须调用 `inner_skills/lark/mcp_lark_update_lark_doc.py`，把最新 `.zip` 以飞书原生【文件块 (File Block)】形式插入到说明飞书文档最顶部（`BLOCK_BEGIN`，即标题下方）。
- **元数据打包**：收集并打包新技能或更新技能的元数据（技能编号、名称、功能描述、技能说明文档链接、技能目录路径、zip 路径、飞书云盘文件链接、创建/更新日期）。
- **调用归档员**：**直接调用 `omni-asset-archiver` 技能**，将上述元数据作为参数传递给归档员。
- **执行目标**：由 `omni-asset-archiver` 作为“唯一物理写入网关”完成向【专属技能清单】或【图书馆】台账的写入。**强制要求归档员遵循 `feishu-doc-writing-guide` 的 RAW 原子锁规范。**

## 约束条件与护栏
- **唯一入口制**：任何“造/改技能”任务，必须以此技能为入口，禁止绕过直接使用 `aime-skill-creator`。
- **防脱节修改铁律（Modify Pipeline）**：修改现有技能时，**严禁 Agent 直接使用代码编辑器私自篡改底层代码**，必须通过本流水线触发。
- **双轨校验（Diff Check）强制熔断**：若是升级现有技能，系统必须校验底层代码（如 `.py`）与顶层说明书（`SKILL.md`）是否**同时修改**。若只改代码未改说明书，立刻报错熔断，拒绝保存。
- **强制版本号升迁（Version Bump）**：每次修改技能，必须在 `SKILL.md` 顶部强制更新版本号，并在文档内写明更新日志（Changelog），确保主脑调用时指令绝对同频。
- **失败重试**：任何一步（尤其是云盘发布、文档挂载、入库和画廊同步）失败，必须输出明确的 `Error` 并尝试重试，严禁“假装成功”。
- **单次闭环**：所有步骤必须在同一次子代理（SubAgent）执行中完成。
- **权限申明**：所有涉及飞书操作的脚本必须设置 `include_secrets=true`。
- **高权限通道**：涉及飞书文档、云盘与文件块写入时，优先复用 `feishu-doc-writing-guide` 的权限治理规则与系统自带 `lark` MCP。

## Zip 发布执行要求
- 运行 `scripts/register_skill.py` 时，必须提供 `--skill-dir` 与说明文档 URL（`--path`）。缺失任一参数时，必须熔断失败。
- 涉及飞书云盘上传、权限赋予、文档挂载时，必须通过 `bash` 工具直接执行，并设置 `include_secrets=true`。
- `scripts/register_skill.py` 的输出 `metadata.json` 必须包含 `zip_path`、`drive_file_url` 与 `doc_link`，用于后续归档。
- 文档挂载默认使用 `BLOCK_BEGIN` 插入，确保文件块位于标题正下方。

## 更新日志 (Changelog)
- **V5**: 新增技能目录自动压缩、飞书云盘上传、`yuqinan@bytedance.com` Full Access 赋权，以及通过 `lark` MCP 自动回挂原生 File Block 到说明文档顶部。
- **V4**: 架构解耦，剥离飞书表格物理写入逻辑，改为调用 `omni-asset-archiver` 技能作为归档网关。

## 操作示例
Skill 资源位于 `user_skills/skill-forge-pipeline-v4`，**文档中所有相对路径/命令均相对于此目录**：
- 读取/编辑：使用 `view_skill` 或编辑器操作本目录。
- 执行流水线辅助脚本：`cd user_skills/skill-forge-pipeline-v4 && python3 scripts/register_skill.py --name "skill-name" --desc "skill-desc" --path "https://bytedance.larkoffice.com/docx/xxx" --skill-dir "user_skills/target-skill" --id "PACK-ID"`
