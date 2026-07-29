---
name: skill-forge-pipeline-v4
version: 5.12
description: 创建、升级、打包、发布并归档 Aime 自制技能。适用于新技能锻造、既有技能迭代、技能上线发布和台账归档场景。
---

# 技能锻造流水线 (Forge Pipeline V5.12)

本技能负责 Aime 系统中技能的创建、修改与自动化部署。它通过集成 `aime-skill-creator`、`cyber-inspiration-generator`、`omni-asset-archiver` 与飞书高权限挂载链路，确保每一个技能的生命周期都得到完整记录。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为“准备绕过护栏”，必须立刻停下并回到 SOP：

- “先把技能产出/打包传上去，回头再补说明文档。”
- “这次只是小改动，版本号就不 bump 了。”
- “飞书写入/赋权失败我先跳过，先给你本地路径就算交付。”
- “自检脚本麻烦，先不跑。”
- “我大概知道风险等级，就不做分级判断了。”

## Red Flags（危险信号）

出现任意一条，必须熔断或要求用户确认（不得继续“假装成功”）：

- 没有执行 `CDA-Guardrails-Selfcheck`，就要进入打包/发布/归档。
- 升级技能只改了代码（`.py`）但没有同步修改说明书（`SKILL.md`）。
- 涉及“复盘报告 / 故障修复报告 / 架构演进报告 / 归档”类技能升级，但 `SKILL.md` 的 Workflow / SOP 中没有显式写入【文档生动化标准】。
- 涉及飞书资产写入/赋权/文件块挂载但没有 `include_secrets=true`。
- 输出中出现“应该/大概/可能/我猜/先跳过”，但没有可验证的 RAW 回读证据。

## Verification（强制验收清单）

当你宣称“流水线完成”时，必须同时满足：

1. **CDA 自检通过**：`scripts/cda_guardrails_selfcheck.py` 退出码为 0，并清晰输出风险等级与三层覆盖情况。
2. **双轨校验通过**：升级技能时，`SKILL.md` 与底层代码（如 `.py`）必须同时有变更（否则立刻熔断）。
3. **Zip 发布闭环**：`scripts/register_skill.py` 生成的 `metadata.json` 中必须包含 `zip_path`、`drive_file_url`、`doc_link`、`wiki_url`、`wiki_node_token`。
4. **说明文档回挂验收**：回捞下载最新文档，确认标题下方存在最新 zip 的原生 File Block（非纯文本链接）。
5. **Wiki 归档验收**：说明文档必须已成功迁入目标 Wiki 节点；若 Wiki Mount Phase 失败，发布流程必须立刻熔断，不得继续落盘 `metadata.json` 或宣称发布成功。
6. **归档台账验收**：对【专属技能清单】写入必须走 RAW 原子锁（写→等 2s→读回核对），不一致立刻熔断。
7. **生动化标准验收**：若目标技能属于报告生成、修复总结、架构演进或归档类能力，`SKILL.md` 中必须存在可执行的【文档生动化标准】条款，并明确联动 `cyber-inspiration-generator` 与“头部前置嵌入”要求。

## 适用场景

- **技能创建与重构**：从零构建或升级现有技能。
- **技能资产回挂**：需要把最新技能目录压缩包自动上传到飞书云盘，并挂载回对应说明文档。

## 强制原子工作流 (Atomic Transaction Workflow)

必须在一次子任务执行中**闭环且强制**地完成以下三个步骤。严禁在完成第一步后等待用户确认或跳过后续步骤。

### 1. Forge 锻造（核心逻辑编写）

作为顶层代理，直接向下调起内置技能 `inner_skills/aime-skill-creator`。

- **执行目标**：按照 `aime-skill-creator` 的 SOP 完成核心 `SKILL.md` 编写、目录初始化、验证及打包（Pack）。
- **报告类技能附加要求**：若目标技能负责复盘报告、故障修复报告、架构演进报告或归档，则必须在 Forge 阶段把【文档生动化标准】写入该技能的 Workflow / SOP；标准中需明确“先调用 `cyber-inspiration-generator` 生成故事与视觉卡片，再前置嵌入飞书文档头部概览区，最后才允许正文写入或归档”。

#### ✅ Checkpoint：CDA-Guardrails-Selfcheck（强制熔断）

> 目标：把“写在文档里的规则”固化成 **认知（L1）+ 默认（L2）+ 断言（L3）** 三层物理护栏。

1) **风险分级决策器（自动判定）**

- **高风险**（触发任一条即高风险）：写操作 / 不可逆 / 权限变更 / 并发写 / 操作飞书资产（docx/sheets/base/file）/ 操作日历
- **中风险**：读为主，但输出会被直接作为“写指令/脚本输入”
- **低风险**：纯检索/总结

2) **三层护栏自检清单（按风险等级强制）**

- **高风险 → L1 + L2 + L3 必须齐备**
- **中风险 → 至少 L1 + L2**
- **低风险 → 至少 L1**

其中：

- **L1 认知层（顶置反合理化三件套）**：`SKILL.md` 顶部是否存在 **Common Rationalizations / Red Flags / Verification**？
- **L2 默认层（合规默认值）**：是否显式提供“合规默认值”，且默认值本身就不诱导违规路径？
- **L3 断言层（运行时物理熔断）**：副作用发生前是否有 `validate_*()` / `assert_*` 一类 runtime gate？失败是否 `raise`？

3) **执行方式（必须跑脚本，失败即熔断）**

```bash
cd user_skills/skill-forge-pipeline-v4
python3 scripts/cda_guardrails_selfcheck.py --skill-dir "user_skills/<target-skill>" --risk auto
```

- 若脚本输出 `FAILED` 或退出码非 0：**Forge 阶段立刻熔断**，不得进入 Celebrate / Archive。
- 反例库与模板位于：`resources/cda_guardrails/`（用于 Forge 时“一键复制 + 反例对照修正”）。

#### 飞书说明文档模板升级（头尾双加持）

自动生成的飞书说明文档（Readme / Document）必须包含以下固定结构，并且：

- **顶部加持**：在「技能简介」之后，紧跟新增「🔑 触发词」模块。
- **底部加持**：在「核心架构 / SOP / 约束条件」之后，文末追加「📖 案例实录 (Best Practice)」模块。

模板骨架如下（生成文档时需保留同名标题与占位符）：

````markdown
## 📌 技能简介
（用 1~3 句话说明：它解决什么问题、适用谁、带来什么收益。）

## 🔑 触发词
- 核心关键词：
  - <关键词1>
  - <关键词2>
- 典型指令示例：
  > <示例指令1>
  > <示例指令2>

## ⚙️ 核心架构 / SOP / 约束条件
（说明核心流程、输入输出、边界与失败重试策略。）

## 📖 案例实录 (Best Practice)
- 🧑‍💻 用户输入：
  ```text
  <用户的原始输入>
  ```
- 🤖 标准输出：
  ```text
  <标准输出示例>
  ```
````

- **必须产出**：技能名称、描述、包 ID、目标技能目录路径。

### 2. Celebrate 庆祝（V3 赛博灵感）

只要技能打包成功，必须**无缝且强制**调起 `cyber-inspiration-generator` (V3)。

- **视觉生成**：调用 `image-generate` 生成一张 16:9 的赛博朋克风 AI 视觉图。
- **灵感铸造**：生成 V3 版本的赛博朋克风灵感卡片，文案需采用 Aime 护主小精灵视角的双轨剧本（小说+说明）。
- **画廊同步**：强制将卡片元数据、截图及文案附加到 V3 画廊多维表格：`https://bytedance.larkoffice.com/base/PRbvbUyLqaeITqsXNMRcRCM5nhh?table=tblHHVXl9ObjSyRw`。

### 3. Archive 入库（图书馆台账 + Zip 资产发布）

到了“入库”环节，流水线默认**不直接写飞书表格**（核心入库仍由 `omni-asset-archiver` 作为唯一网关负责），但为了实现「版本同步总线（SSOT）」：

- 必须以目标技能的 `SKILL.md` Frontmatter `version:` 为 **单一事实来源**。
- 在归档执行时，必须完成版本号升迁（Major +1.0 / Minor +0.1），并将新版本号 **回写覆盖** 本地目标技能 `SKILL.md`。
- 同时必须通过 `bytedcli-auth` + MCP `lark_sheets_update`，对飞书台账【专属技能清单】的【版本号】列做定向覆写，并执行“写 → 等 2s → 读回核对”的 RAW 级验收。
- 若说明文档中存在版本标识，应通过 MCP 将其替换为最新版本号。

- **Zip 打包**：在最后阶段强制运行 `scripts/register_skill.py`，传入 `--skill-dir`，将目标技能目录（如 `user_skills/xxx/`）打包为同级 `.zip` 文件。
- **云盘发布**：`scripts/register_skill.py` 必须将 `.zip` 发布到飞书云盘，并通过 `feishu-doc-writing-guide` 的 MCP / personal-space 修复链路为 `yuqinan@bytedance.com` 恢复可管理访问权；严禁再用 `AIME_USER_CLOUD_JWT` 直调 Drive Permission API。
- **文档挂载**：`scripts/register_skill.py` 必须调用 `inner_skills/lark/mcp_lark_update_lark_doc.py`，把最新 `.zip` 以飞书原生【文件块 (File Block)】形式插入到说明飞书文档最顶部（`BLOCK_BEGIN`，即标题下方）。
- **Wiki Mount Phase**：在 ZIP 原生文件块回挂完成后、`metadata.json` 落盘前，必须调用飞书 Wiki MCP 挂载链路（如 `mcp_lark_move_lark_doc.py`），将说明文档迁入「Aime 技能库」根节点或 `--wiki-node-token` 指定节点。该步骤属于发布成功的强契约；一旦迁移失败，必须立刻熔断，禁止继续 metadata 落盘、归档写台账或宣称发布完成。
- **元数据打包**：收集并打包新技能或更新技能的元数据（技能编号、名称、功能描述、技能说明文档链接、技能目录路径、zip 路径、飞书云盘文件链接、Wiki 链接、Wiki 节点 token、创建/更新日期）。
- **调用归档员**：**直接调用 `omni-asset-archiver` 技能**，将上述元数据作为参数传递给归档员。
- **执行目标**：由 `omni-asset-archiver` 作为“唯一物理写入网关”完成向【专属技能清单】或【图书馆】台账的写入。**强制要求归档员遵循 `feishu-doc-writing-guide` 的 RAW 原子锁规范。**
- **本技能自升级额外要求**：本次升级的版本号与变更说明必须同步写入 `CHANGELOG.md`，并追加更新到对应飞书 Wiki 说明文档。
- **Post-Forge Git Push Hook**：`scripts/register_skill.py` 在 metadata 写入完成后必须自动调用 `user_skills/scripts/post_forge_git_push.sh <skill_name> <version>`，将 `user_skills/` 最新变更 commit+push 到 `https://github.com/Yu1ocean/qi-skills`。若需要调试跳过，可显式设置 `SKIP_POST_FORGE_GIT_PUSH=1`，否则缺失 hook 或 push 失败均视为发布链路失败。

## 约束条件与护栏

- **唯一入口制**：任何“造/改技能”任务，必须以此技能为入口，禁止绕过直接使用 `aime-skill-creator`。
- **防脱节修改铁律（Modify Pipeline）**：修改现有技能时，**严禁 Agent 直接使用代码编辑器私自篡改底层代码**，必须通过本流水线触发。
- **双轨校验（Diff Check）强制熔断**：若是升级现有技能，系统必须校验底层代码（如 `.py`）与顶层说明书（`SKILL.md`）是否**同时修改**。若只改代码未改说明书，立刻报错熔断，拒绝保存。
- **强制版本号升迁（Version Bump）**：每次修改技能，必须在 `SKILL.md` 顶部强制更新版本号，并在文档内写明更新日志（Changelog），确保主脑调用时指令绝对同频。
- **失败重试**：任何一步（尤其是云盘发布、文档挂载、入库和画廊同步）失败，必须输出明确的 `Error` 并尝试重试，严禁“假装成功”。
- **单次闭环**：所有步骤必须在同一次子代理（SubAgent）执行中完成。
- **权限申明**：所有涉及飞书操作的脚本必须设置 `include_secrets=true`。
- **高权限通道**：涉及飞书文档、云盘与文件块写入时，优先复用 `feishu-doc-writing-guide` 的权限治理规则与系统自带 `lark` MCP。

## 合规默认值（Defaults）

- `--user-email` 默认：`yuqinan@bytedance.com`（ZIP 资产访问修复默认目标用户；经 MCP personal-space 链路恢复可管理权限）
- 文档挂载默认插入点：`BLOCK_BEGIN`（标题正下方）
- `--wiki-node-token` 默认：`GU0ewkyaGi4i5nkwBtNcM3aPn9g`（Aime 技能库根节点）
- 写后即读 RAW 校验：默认开启（任何不一致必须熔断）
- **`--initial-version` 默认：`1.1`**（首次发布起始版本号）
  - 当 `SKILL.md` 当前版本仍处于 `0.x` 脚手架阶段时，流水线判定为「首次发布」，**会忽略 `--bump`，直接将版本设为 `1.1`**，不再做 `0.x → 0.x+0.1` 的小迭代。
  - 已经 ≥ `1.0` 的技能，按原 `--bump major|minor` 规则升迁，不受影响。
  - 如需自定义首发版本，可显式传 `--initial-version 2.0` 覆盖默认；如需强制指定任意目标版本，可显式传 `--new-version 0.2`。

## 更新日志 (Changelog)

- **V5.12**: 新增 Post-Forge Git Push Hook。
  - `register_skill.py` 在 metadata 写入成功后自动调用 `user_skills/scripts/post_forge_git_push.sh`，将 `user_skills/` 的新建或迭代技能变更提交并推送到 GitHub 仓库 `Yu1ocean/qi-skills`。
  - 新增 `SKIP_POST_FORGE_GIT_PUSH=1` 调试开关；默认不跳过，hook 缺失或 push 失败时发布链路直接失败，避免“锻造成功但 GitHub 漏同步”的幽灵资产。
- **V5.11**: 修复 `grant drive full_access` 阶段的 `99991668 Invalid access token`。
  - `register_skill.py` 不再把 `AIME_USER_CLOUD_JWT` 当作飞书 Access Token 直调 Drive Permission API。
  - ZIP 附件回挂后，改为调用 `feishu-doc-writing-guide` 的兼容包装器，走 `move_lark_doc -> personal` 的 MCP 修复链路恢复资产访问权，随后继续 metadata 落盘与台账写入。
- **V5.10**: 修复 ZIP 附件 `file_token` 回捞断点，新增“下载最新 `.lark.md` 并解析附件 token”兜底链路。
  - 当 `mcp_lark_update_lark_doc` 的输出不再直接暴露 `file_token`，且 `list_doc_file_blocks` fallback 未拿到新插入 File Block 的 token 时，`register_skill.py` 会自动下载最新文档并从文档内容中回捞 `/file/<token>` / `file_token` 线索。
  - 只有三层路径（attach_output → 文档块 diff → 文档 markdown introspection）全部失败时，才允许硬熔断，避免权限闭环与 metadata 验收被单点解析漂移打断。
- **V5.7**: 新增 Wiki Mount Phase，发布成功必须完成说明文档迁入 Aime 技能库 Wiki。
  - `register_skill.py` 在 ZIP 文件块回挂完成后、metadata 落盘前，强制调用 `mcp_lark_move_lark_doc.py` 将说明文档迁入 Wiki 节点。
  - `metadata.json` 新增 `wiki_url`、`wiki_node_token` 断言字段，用于归档与验收。
  - 若 Wiki 挂载失败，发布流程立即熔断，不再允许继续 metadata 落盘或宣称发布成功。
- **V5.6**: 首次发布判定从枚举触发值升级为 `Major == 0`。
  - 废除写死的 `0.0 / 0.1 / 0.2` 触发集合，统一将所有 `0.x` 视为脚手架阶段。
  - 只要当前版本仍处于 `0.x`，Archive 阶段都会忽略 `--bump`，强制设为 `1.1`（或 `--initial-version` 指定值），不再做 `+0.1` 小步迭代。
- **V5.5**: 新增「首次发布起始版本号」机制。
  - 新增 `--initial-version` CLI 参数，默认 `1.1`。
  - 当目标技能 `SKILL.md` 当前版本仍为脚手架占位值（`0.0` / `0.1` / `0.2`）时，流水线判定为首次发布，**强制将版本设为 `1.1`**，跳过 `0.x → 0.x+1` 的尴尬段位。
  - 已 ≥ `1.0` 的存量技能不受影响，继续按 `--bump major|minor` 升迁。
- **V5.4**: 新增“文档生动化标准”护栏：当升级报告生成/修复总结/架构演进/归档类技能时，Forge 阶段必须把该标准写入 Workflow / SOP，并在 Verification 中强制验收。
- **V5.2**: 新增 `CDA-Guardrails-Selfcheck` Forge Checkpoint（风险分级 + 三层护栏自检 + 失败即熔断），并下沉反例库/模板到 `resources/cda_guardrails/`。
- **V5.1**: 飞书说明文档（Readme / Document）模板升级，新增「🔑 触发词」与「📖 案例实录 (Best Practice)」的头尾双加持结构。
- **V5**: 新增技能目录自动压缩、飞书云盘上传、`yuqinan@bytedance.com` Full Access 赋权，以及通过 `lark` MCP 自动回挂原生 File Block 到说明文档顶部。
- **V4**: 架构解耦，剥离飞书表格物理写入逻辑，改为调用 `omni-asset-archiver` 技能作为归档网关。

## 操作示例

Skill 资源位于 `user_skills/skill-forge-pipeline-v4`，**文档中所有相对路径/命令均相对于此目录**：

- 读取/编辑：使用 `view_skill` 或编辑器操作本目录。
- 执行流水线辅助脚本：

```bash
cd user_skills/skill-forge-pipeline-v4 \
  && python3 scripts/register_skill.py \
    --name "skill-forge-pipeline-v4" \
    --desc "自动化技能创建、升级、打包发布与归档流水线（含 CDA Guardrails 自检）" \
    --path "https://bytedance.larkoffice.com/docx/HgY3dJBPfowjJfxWnxWcvItJncg" \
    --wiki-node-token "GU0ewkyaGi4i5nkwBtNcM3aPn9g" \
    --bump minor \
    --skill-dir "user_skills/skill-forge-pipeline-v4" \
    --id "SKILL-FORGE-PIPELINE"
```
