---
name: skill-forge-pipeline-v4
version: 5.18
description: 创建、升级、打包、发布并归档 Aime 自制技能。适用于新技能锻造、既有技能迭代、技能上线发布和台账归档场景。
---

# 技能锻造流水线 (Forge Pipeline V5.18)

本技能负责 Aime 系统中技能的创建、修改与自动化部署。它通过集成 `aime-skill-creator`、`cyber-inspiration-generator`、`omni-asset-archiver` 与飞书高权限挂载链路，确保每一个技能的生命周期都得到完整记录。

## Common Rationalizations（常见借口库）

以下借口一旦出现，视为“准备绕过护栏”，必须立刻停下并回到 SOP：

- “先把技能产出/打包传上去，回头再补说明文档。”
- “这次只是小改动，版本号就不 bump 了。”
- “飞书写入/赋权失败我先跳过，先给你本地路径就算交付。”
- “赋权那步只是个 WARNING，不影响发布，照样报成功。”
- “底层 MCP 脚本没了，我 try/except 兜一下打条提示就行。”
- “自检脚本麻烦，先不跑。”
- “我大概知道风险等级，就不做分级判断了。”
- “飞书镜像写成功了，本地 SSOT 回头再补。”
- “只有一轨回读失败，问题不大，先算完成。”

## Red Flags（危险信号）

出现任意一条，必须熔断或要求用户确认（不得继续“假装成功”）：

- 没有执行 `CDA-Guardrails-Selfcheck`，就要进入打包/发布/归档。
- 升级技能只改了代码（`.py`）但没有同步修改说明书（`SKILL.md`）。
- 涉及“复盘报告 / 故障修复报告 / 架构演进报告 / 归档”类技能升级，但 `SKILL.md` 的 Workflow / SOP 中没有显式写入【文档生动化标准】。
- 涉及飞书资产写入/赋权/文件块挂载但没有 `include_secrets=true`。
- 输出中出现“应该/大概/可能/我猜/先跳过”，但没有可验证的 RAW 回读证据。
- **仅凭 `git push` 的退出码判定成功**，没有回读远端 `refs/heads/main` 的 SHA 与本地 HEAD 做比对。
- Post-Forge Git Push 仍在执行 `git push origin main`（依赖本地可能陈旧的 `main` ref），而非 `git push origin HEAD:main`。
- ZIP 文件块只调用了 `lark-cli docs +media-insert`（默认追加到文档末尾）就宣称「已挂到标题下方」，没有 `block_move_after` 归位 + 首块回读断言。
- 涉及本地 SSOT + 飞书镜像双轨写入，但只验证了单轨。
- 写入后没有做 RAW read-after-write 双轨 ID 一致性断言。
- 双轨断言失败却未写入孤儿待修复死信队列（`.ephemeral_pool/orphan_decisions.jsonl`）。
- Archive 阶段只 append ZIP 文件块、未清理同名旧块（导致说明文档堆积历史版本 ZIP）。
- 未做「本技能 ZIP 块数量 == 1」回读断言，就宣称文件块回挂完成。
- **赋权失败被静默成 WARNING（如 `⚠️ drive asset access repair skipped: ...`）却仍宣称发布成功** —— 用户拿到的是「只能看不能管」的孤儿 ZIP 资产。
- 仍在调用已下线的 `mcp_lark_move_lark_doc.py` / `ensure_doc_in_personal.py` 做资产赋权。
- ZIP 云盘赋权后没有 `lark-cli drive +member-list` 的 RAW 回读证据（member_id + perm）。
- Celebrate 阶段引用不存在的 V3 脚本 / 模板（`assemble_card_v3.py`、`card_template_v3.html`、`update_bitable_v3.py`），或画廊记录落到旧灵感台账 `tbly6lJBR0QYTBfW` 而非 V3 画廊 `tblHHVXl9ObjSyRw`。
- Celebrate 画廊同步失败后静默放行（输出 "proceeding to ensure workflow continuity" 一类话术）而未熔断。
- 自动删除了非本技能的 ZIP 文件块（异物块属他人资产，只允许报告 + 人工确认）。

## Verification（强制验收清单）

当你宣称“流水线完成”时，必须同时满足：

1. **CDA 自检通过**：`scripts/cda_guardrails_selfcheck.py` 退出码为 0，并清晰输出风险等级与三层覆盖情况。
2. **双轨校验通过**：升级技能时，`SKILL.md` 与底层代码（如 `.py`）必须同时有变更（否则立刻熔断）。
3. **Zip 发布闭环**：`scripts/register_skill.py` 生成的 `metadata.json` 中必须包含 `zip_path`、`drive_file_url`、`doc_link`、`wiki_url`、`wiki_node_token`。
4. **说明文档回挂验收**：回捞下载最新文档，确认标题下方存在最新 zip 的原生 File Block（非纯文本链接）。
5. **Wiki 归档验收**：说明文档必须已成功迁入目标 Wiki 节点；若 Wiki Mount Phase 失败，发布流程必须立刻熔断，不得继续落盘 `metadata.json` 或宣称发布成功。
6. **归档台账验收**：对【专属技能清单】写入必须走 RAW 原子锁（写→等 2s→读回核对），不一致立刻熔断。
7. **生动化标准验收**：若目标技能属于报告生成、修复总结、架构演进或归档类能力，`SKILL.md` 中必须存在可执行的【文档生动化标准】条款，并明确联动 `cyber-inspiration-generator` 与“头部前置嵌入”要求。
8. **云盘 ZIP 赋权验收**：Archive 阶段的 ZIP 赋权必须输出 `lark-cli drive +member-list` RAW 回读证据（目标 open_id/owner_id + `perm == full_access`）。赋权失败必须熔断，禁止以 WARNING 形式放行。

9. **Git 同步远端断言验收**：Post-Forge Git Push 之后，远端 `origin/main` 的 commit SHA **必须严格等于**本地 `git rev-parse HEAD`（通过 `git ls-remote origin refs/heads/main` 回读比对）。只要不一致，即判定 push 未生效，hook 必须以非 0 退出码熔断，禁止宣称「已 push 到 qi-skills」。
10. **文件块位置断言验收**：ZIP 原生 File Block 必须位于说明文档**第一个正文块**（BLOCK_BEGIN，标题正下方）。`register_skill.py` 在 `+media-insert` 之后必须执行 `block_move_after`（anchor = 文档 root token）归位，并回读文档 XML 断言首个正文块 id == 新建文件块 id；不一致立刻 `raise` 熔断。
11. **双轨原子写入验收**：凡涉及「决策台账写入飞书镜像」的节点，本地 SSOT `memory/topics/decision-registry.md` 末条决策 ID 与飞书镜像末行 ID **必须一致**，且必须输出双轨回读证据（`assert_local_track` / `assert_mirror_track` 的 evidence）。任一轨失败即 `raise` 熔断并落孤儿死信队列，禁止宣称完成。
12. **文件块唯一性断言**：Archive 阶段回挂 ZIP 后，必须回读说明文档并断言「属于本技能的 ZIP 文件块数量恰好为 1」且其 block_id/file_token 等于本次新块。不满足时必须显式输出残留清单与人工解法（允许非熔断，禁止静默）。异物块（其他技能的 ZIP）必须列出 block_id + 文件名交由人工拍板，严禁自动删除。

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

### 2. Celebrate 庆祝（赛博灵感卡片）

只要技能打包成功，必须**无缝且强制**调起 `cyber-inspiration-generator`。

- **正式入口（唯一）**：`user_skills/skill-forge-pipeline-v4/scripts/celebrate_skill.py`。该脚本在启动前执行**依赖存在性断言**，任一依赖缺失即 `raise` 熔断；画廊同步失败同样 `raise`，**禁止**再出现 "proceeding to ensure workflow continuity" 一类静默放行。
- **依赖清单（必须真实存在，禁止引用任何 `_v3` 幽灵资产）**：
  - `user_skills/cyber-inspiration-generator/assets/card_template.html`
  - `user_skills/cyber-inspiration-generator/scripts/assemble_card.py`（签名：`subject story fact image_url template output`）
  - `user_skills/cyber-inspiration-generator/scripts/capture_screenshot.py`
  - `user_skills/cyber-inspiration-generator/scripts/sync_gallery.py`（通用化画廊同步，取代历史一次性 `sync_gallery_*.py`）
- **视觉生成**：调用 `image-generate` 生成一张 16:9 的赛博朋克风 AI 视觉图。
- **灵感铸造**：文案采用 Aime 护主小精灵视角的双轨剧本（【小说】+【说明】）。
- **画廊同步（唯一正式表）**：`base PRbvbUyLqaeITqsXNMRcRCM5nhh` / `table tblHHVXl9ObjSyRw` / 附件字段 `fldOBqrqET`，即 `https://bytedance.larkoffice.com/base/PRbvbUyLqaeITqsXNMRcRCM5nhh?table=tblHHVXl9ObjSyRw`。
  ⚠️ `cyber-inspiration-generator/scripts/update_bitable.py` 指向的 `tbly6lJBR0QYTBfW` 是**旧灵感台账**，仅作历史兼容，严禁用于 Celebrate 画廊同步。
- **调用示例**（`include_secrets=true`）：

```bash
python3 user_skills/skill-forge-pipeline-v4/scripts/celebrate_skill.py \
  --name "<skill-name>" --skill-id "<SKILL-ID>-V<version>" \
  --card-title "<卡片标题>" --skill-type "防错机制" --status "已上线" \
  --image-url "<image_url>" --deployed-url "<deployed_url>" \
  --story "<【小说】...>" --fact "<【说明】...>" \
  --screenshot "screenshot.png"
```

- **验收**：必须输出 `record_id` + `table_id` + 部署 URL，并有 `+record-get` RAW 回读证据（附件字段非空）。

### 3. Archive 入库（图书馆台账 + Zip 资产发布）

到了“入库”环节，流水线默认**不直接写飞书表格**（核心入库仍由 `omni-asset-archiver` 作为唯一网关负责），但为了实现「版本同步总线（SSOT）」：

- 必须以目标技能的 `SKILL.md` Frontmatter `version:` 为 **单一事实来源**。
- 在归档执行时，必须完成版本号升迁（Major +1.0 / Minor +0.1），并将新版本号 **回写覆盖** 本地目标技能 `SKILL.md`。
- 同时必须通过 `bytedcli-auth` + MCP `lark_sheets_update`，对飞书台账【专属技能清单】的【版本号】列做定向覆写，并执行“写 → 等 2s → 读回核对”的 RAW 级验收。
- 若说明文档中存在版本标识，应通过 MCP 将其替换为最新版本号。

- **Zip 打包**：在最后阶段强制运行 `scripts/register_skill.py`，传入 `--skill-dir`，将目标技能目录（如 `user_skills/xxx/`）打包为同级 `.zip` 文件。
- **云盘发布**：`scripts/register_skill.py` 必须将 `.zip` 发布到飞书云盘，并调用 `feishu-doc-writing-guide/scripts/grant_doc_permissions.py`（底层 `lark-cli drive +member-add` + `+member-list` RAW 回读断言）为 `yuqinan@bytedance.com` 赋 `full_access`。严禁再用 `AIME_USER_CLOUD_JWT` 直调 Drive Permission API，严禁调用已下线的 `move_lark_doc` / `ensure_doc_in_personal.py`。
- **赋权失败即熔断（V5.18）**：该步骤**不允许任何静默降级**。原实现在捕获异常后，只要报错含 `move_lark_doc` 就 return 一条 WARNING 字符串，导致赋权长期从未真正发生（典型「假成功」）。现已删除该兜底：赋权失败直接 `raise`，发布链路熔断。
- **文档挂载**：`scripts/register_skill.py` 必须调用 `inner_skills/lark/mcp_lark_update_lark_doc.py`，把最新 `.zip` 以飞书原生【文件块 (File Block)】形式插入到说明飞书文档最顶部（`BLOCK_BEGIN`，即标题下方）。
  - **位置归位与断言（V5.14 新增）**：实际链路使用 `lark-cli docs +media-insert`，其默认行为是**追加到文档末尾**，会静默违反「标题正下方」契约。因此插入后必须：① 从输出解析新文件块 `block_id`；② 执行 `lark-cli docs +update --command block_move_after --block-id <文档 root token> --src-block-ids <block_id>` 将其移到 index 0；③ 回读文档 XML，断言首个正文块 id 等于该 `block_id`，否则 `raise` 熔断。
- **Archive 步骤文件块替换规则（V5.16 新增，幂等替换而非 append）**：ZIP 回挂必须是**幂等替换**，同一说明文档在任意时刻只允许存在 1 个属于本技能的 ZIP 文件块。执行顺序不可颠倒：
  1. **插入前枚举**：调用 `list_doc_zip_file_blocks(doc_url)`（走 `lark-cli docs +fetch --doc-format xml --detail with-ids`，解析 `<figure><source name=... token=...>`）快照现有全部 ZIP 文件块。
  2. **插新块 → 归位 → 断言**：先 `+media-insert` 插入新块，再 `move_block_to_doc_begin` 移到 index 0，再 `assert_zip_block_at_doc_begin` 断言通过。**必须先确认新块落位成功，再进入删除环节**，避免「删完插失败」导致文档裸奔。
  3. **删同名旧块**：用 `is_own_skill_zip()` 识别属于本技能的旧 ZIP（文件名匹配 skill 名，允许 `_v1.2` / `-1.2` / ` (1)` 等版本后缀变体），且 block_id ≠ 本次新块；用 `lark-cli docs +update --command block_delete --block-id <逗号分隔>` 批量物理删除。
  4. **删除后 RAW 回读断言**：`sleep 2s` 后重新枚举，断言属于本技能的 ZIP 块**数量恰好为 1** 且 block_id == 新块。不一致时打印醒目 WARNING 并输出残留清单（此处非熔断，但**严禁静默**）。
  5. **异物块只报告不删除**：文件名与当前 skill 名不符的 ZIP 块视为「异物块」（他人资产）。本流水线既不为其他技能往本文档插块，也**不自动删除**异物块，只输出 block_id + 文件名清单交由人工拍板。
  6. **枚举失败降级**：若枚举链路因权限/scope/接口变更失败，降级为「只插入不删除」并打印醒目 WARNING，**不熔断整条流水线**；同时禁止把失败静默成空列表（枚举接口返回非 0 code 必须 `raise`）。
- **Wiki Mount Phase**：在 ZIP 原生文件块回挂完成后、`metadata.json` 落盘前，必须调用飞书 Wiki MCP 挂载链路（如 `mcp_lark_move_lark_doc.py`），将说明文档迁入「Aime 技能库」根节点或 `--wiki-node-token` 指定节点。该步骤属于发布成功的强契约；一旦迁移失败，必须立刻熔断，禁止继续 metadata 落盘、归档写台账或宣称发布完成。
- **元数据打包**：收集并打包新技能或更新技能的元数据（技能编号、名称、功能描述、技能说明文档链接、技能目录路径、zip 路径、飞书云盘文件链接、Wiki 链接、Wiki 节点 token、创建/更新日期）。
- **调用归档员**：**直接调用 `omni-asset-archiver` 技能**，将上述元数据作为参数传递给归档员。
- **执行目标**：由 `omni-asset-archiver` 作为“唯一物理写入网关”完成向【专属技能清单】或【图书馆】台账的写入。**强制要求归档员遵循 `feishu-doc-writing-guide` 的 RAW 原子锁规范。**
- **本技能自升级额外要求**：本次升级的版本号与变更说明必须同步写入 `CHANGELOG.md`，并追加更新到对应飞书 Wiki 说明文档。
- **Post-Forge Git Push Hook**：`scripts/register_skill.py` 在 metadata 写入完成后必须自动调用 `user_skills/scripts/post_forge_git_push.sh <skill_name> <version>`，将 `user_skills/` 最新变更 commit+push 到 `https://github.com/Yu1ocean/qi-skills`。若需要调试跳过，可显式设置 `SKIP_POST_FORGE_GIT_PUSH=1`，否则缺失 hook 或 push 失败均视为发布链路失败。
  - **推送语义（`HEAD:main`）**：hook 必须执行 `git push origin HEAD:main`，把**当前 HEAD** 显式推到远端 `main`。**严禁** `git push origin main` —— 工作副本 HEAD 常处于特性分支（如 `aime/*`），此时该命令推送的是本地陈旧的 `main` ref，退出码仍为 0，会形成「宣称已同步、GitHub 上却没有新版本」的幽灵资产。
  - **远端 SHA 回读断言（核心护栏）**：push 之后必须执行 `git rev-parse HEAD` 与 `git ls-remote origin refs/heads/main`（或 `git fetch origin main` + `git rev-parse origin/main`）比对两个 commit SHA。**一致才算 PASS；不一致即判定 push 未真正生效，必须以非 0 退出码退出并输出醒目错误。** 禁止仅凭 `git push` 的退出码判定成功。
  - **non-fast-forward 自愈**：若远端已被他人推进导致首次 push 被 reject，hook 需先 `git fetch origin main`，再 `git rebase origin/main`（rebase 冲突则回滚改用 `git merge`），随后**重试 push 一次**；仍失败则以非 0 退出并明确报告「需人工介入」，不得静默吞掉错误。
  - **结构化审计日志**：hook 必须输出 `local_branch` / `local_head`（本地 HEAD SHA）/ `remote_main`（远端 main SHA）/ `assert_result`（PASS 或 FAIL），便于事后审计与幽灵资产追溯。
  - **无新增变更也要断言**：若 `git add user_skills/` 后没有可提交的差异，hook 不得直接 `exit 0` 收工，仍须继续执行 push 与远端 SHA 回读断言（防止历史 commit 未同步被漏判）。

### 4. Git 自动归档（新）

- 调用 `bash user_skills/scripts/post_forge_git_push.sh <skill_name> <version>`。
- 将本次技能变更 commit 并以 `git push origin HEAD:main` 的语义推到 `https://github.com/Yu1ocean/qi-skills`（推 **HEAD**，不推本地 `main` ref）。
- commit message 格式：`feat(skill): upsert <skill_name> <version>`。
- **push 后必须做远端回读断言**：`git ls-remote origin refs/heads/main` 得到的 SHA 必须等于 `git rev-parse HEAD`；不等即 FAIL，hook 以非 0 退出码熔断，流水线不得宣称同步成功。
- 遇到 non-fast-forward：`git fetch origin main` → `git rebase origin/main`（或 merge）→ 重试 push 一次；仍失败则非 0 退出并报告「需人工介入」。
- 日志需包含分支名、本地 HEAD SHA、远端 main SHA 与断言结论（PASS/FAIL）。
- 如 push 失败（网络/凭证问题/断言 FAIL），记录错误并向用户汇报；自动 hook 在正式发布链路中应视为失败熔断，手动补触发场景可作为非阻断告警处理。
- 调试开关 `SKIP_POST_FORGE_GIT_PUSH=1` 语义保持不变：显式跳过整个 hook 并以 0 退出。

## 约束条件与护栏

- **唯一入口制**：任何“造/改技能”任务，必须以此技能为入口，禁止绕过直接使用 `aime-skill-creator`。
- **防脱节修改铁律（Modify Pipeline）**：修改现有技能时，**严禁 Agent 直接使用代码编辑器私自篡改底层代码**，必须通过本流水线触发。
- **双轨校验（Diff Check）强制熔断**：若是升级现有技能，系统必须校验底层代码（如 `.py`）与顶层说明书（`SKILL.md`）是否**同时修改**。若只改代码未改说明书，立刻报错熔断，拒绝保存。
- **强制版本号升迁（Version Bump）**：每次修改技能，必须在 `SKILL.md` 顶部强制更新版本号，并在文档内写明更新日志（Changelog），确保主脑调用时指令绝对同频。
- **失败重试**：任何一步（尤其是云盘发布、文档挂载、入库和画廊同步）失败，必须输出明确的 `Error` 并尝试重试，严禁“假装成功”。
- **单次闭环**：所有步骤必须在同一次子代理（SubAgent）执行中完成。
- **权限申明**：所有涉及飞书操作的脚本必须设置 `include_secrets=true`。
- **高权限通道**：涉及飞书文档、云盘与文件块写入时，优先复用 `feishu-doc-writing-guide` 的权限治理规则与系统自带 `lark` MCP。
- **Git 同步强制触发**：每次 forge/upsert 完成后必须触发 Git push hook，确保 qi-skills 仓库与本地 `user_skills/` 保持同步。
- **自举同频**：forge 自举（对 `skill-forge-pipeline-v4` 自身迭代）时同样需要触发 Git push，并同样接受远端 SHA 回读断言。
- **反假成功铁律（No Fake Success）**：任何“同步/写入/发布”类副作用，都必须有**独立回读证据**（Git 走远端 SHA 比对，飞书走 RAW 回读）。只看命令退出码即宣称成功，视为 P1 缺陷。

## 合规默认值（Defaults）

- `--user-email` 默认：`yuqinan@bytedance.com`（ZIP 资产访问修复默认目标用户；经 MCP personal-space 链路恢复可管理权限）
- 文档挂载默认插入点：`BLOCK_BEGIN`（标题正下方）
- `--wiki-node-token` 默认：`GU0ewkyaGi4i5nkwBtNcM3aPn9g`（Aime 技能库根节点）
- 写后即读 RAW 校验：默认开启（任何不一致必须熔断）
- **`--initial-version` 默认：`1.1`**（首次发布起始版本号）
  - 当 `SKILL.md` 当前版本仍处于 `0.x` 脚手架阶段时，流水线判定为「首次发布」，**会忽略 `--bump`，直接将版本设为 `1.1`**，不再做 `0.x → 0.x+0.1` 的小迭代。
  - 已经 ≥ `1.0` 的技能，按原 `--bump major|minor` 规则升迁，不受影响。
  - 如需自定义首发版本，可显式传 `--initial-version 2.0` 覆盖默认；如需强制指定任意目标版本，可显式传 `--new-version 0.2`。
- 决策镜像台账默认：`https://bytedance.larkoffice.com/wiki/PnnDwYr13imUyVkVPshc46ICnVh`
- 本地 SSOT 默认路径：`memory/topics/decision-registry.md`
- 孤儿死信队列默认路径：`.ephemeral_pool/orphan_decisions.jsonl`
- 双轨 RAW 回读等待默认：`2` 秒（写 → 等 2s → 双轨回读）

## 双轨原子写入约束 (Dual-Track Atomic Write)

关联决策：**DEC-20260821-001**「决策录入必须双轨原子写入，单轨成功即判失败」。

### 适用范围

凡 forge 流程中涉及「决策台账写入飞书镜像」的节点（决策录入、护栏升格、复盘沉淀带出的新决策条目），都必须走本约束。只写飞书镜像不 append 本地 SSOT，会形成**孤儿行**，漂移可长达数天不可见——这是本约束存在的根因。

### 事务块绑定顺序

1. 飞书镜像写入（含 sync 链路自带 RAW 回捞）成功；
2. **立刻**执行本地 SSOT append（`memory/topics/decision-registry.md`）；
3. 两步绑定为一个事务：中间不允许插入任何其他动作，不允许等待用户确认，不允许分两次对话完成。

### 双轨断言规则

- 轨道 A（local）：回读本地文件，解析最后一条 `- id: DEC-...`，断言 == 目标 ID。
- 轨道 B（mirror）：回读飞书镜像末条记录 ID，断言 == 目标 ID。
- 写后等待 2s 再回读；**任一轨回读失败或 ID 不一致 → 立刻 `raise` 熔断，严禁静默成功**。

### 失败即孤儿标记

断言失败或写入失败时，必须把该条目写入死信队列 `.ephemeral_pool/orphan_decisions.jsonl`，字段含 `decision_id` / `failed_track`(local|mirror) / `error` / `timestamp` / `suggested_fix`，并标记 `⚠️[孤儿待修复]`。随后由 `tools/sync_decision_registry.py`（以本地为准修复镜像）或手工补 append 本地后重跑断言收敛。

### 调用示例

```bash
# 前置校验 + 事务计划（零副作用）
python3 user_skills/skill-forge-pipeline-v4/scripts/dual_track_atomic_write.py \
  --dry-run --decision-id DEC-20260821-001 --entry-file /tmp/dec_entry.yaml

# 双轨原子写入（镜像写入 -> 立刻本地 append -> 双轨断言）
python3 user_skills/skill-forge-pipeline-v4/scripts/dual_track_atomic_write.py \
  --decision-id DEC-20260821-001 --entry-file /tmp/dec_entry.yaml

# 事后巡检：只做双轨回读断言
python3 user_skills/skill-forge-pipeline-v4/scripts/dual_track_atomic_write.py \
  --verify-only DEC-20260821-001

# 故障注入自测：人为让某一轨失败，验证 raise + 死信队列链路
python3 user_skills/skill-forge-pipeline-v4/scripts/dual_track_atomic_write.py \
  --verify-only DEC-20260821-001 --inject-failure mirror
```

> 所有调用必须设置 `include_secrets=true`；飞书读写一律走 MCP / `lark-cli` 链路，严禁裸调 OpenAPI。

## 更新日志 (Changelog)

- **V5.18**: 修复 Archive 阶段「ZIP 云盘资产赋权」的 P1 假成功缺陷。
  - 根因：`ensure_drive_asset_access_via_mcp()` → `grant_doc_permissions.py` → `ensure_doc_in_personal.py` → `inner_skills/lark/mcp_lark_move_lark_doc.py`，而该 MCP 脚本已从运行时下线（FileNotFoundError）；`register_skill.py` 捕获异常后只要报错含 `move_lark_doc` 就静默 return WARNING，赋权实际从未执行，用户拿到的是「只能看不能管」的孤儿 ZIP。
  - `register_skill.py`：**删除**该静默 WARNING 兜底，赋权失败直接 `raise` 熔断（反假成功铁律）。
  - `feishu-doc-writing-guide` v7.6：`grant_doc_permissions.py` 重写为 `lark-cli drive +member-add` 赋权 + `lark-cli drive +member-list` RAW 回读断言，含 owner 短路、`1063003` 幂等处理与 email→open_id 解析；`ensure_doc_in_personal.py` 标记失效。
  - Red Flags 新增「赋权失败被静默成 WARNING 仍宣称发布成功」等 4 条；Verification 新增第 8 条「云盘 ZIP 赋权验收」。

- **V5.17**: 修复 Celebrate 阶段「幽灵 V3 资产 + 静默降级」缺陷。
  - `scripts/celebrate_skill.py` 由孤儿脚本升格为 Celebrate **正式入口**：不再引用根本不存在的 `card_template_v3.html` / `assemble_card_v3.py` / `update_bitable_v3.py`，改为调用真实存在的 `assemble_card.py` + `card_template.html` + `capture_screenshot.py` + 新的 `sync_gallery.py`。
  - 新增启动前 L3 存在性断言 `assert_dependencies_exist()`：四个依赖路径任一缺失即 `raise` 熔断；新增 `assert_official_gallery()` 拒绝写入旧灵感台账 `tbly6lJBR0QYTBfW`。
  - 删除「Bitable sync failed, but proceeding to ensure workflow continuity」静默放行分支，所有子步骤改为 `run_or_raise`，失败即熔断。
  - 配套：`cyber-inspiration-generator` v2.1 新增通用化 `scripts/sync_gallery.py`（参数化 + 5 条 L3 断言 + 写后 `+record-get` RAW 回读），取代每次 forge 手写一次性 `sync_gallery_*.py` 的技术债。
  - SKILL.md Celebrate 章节写明正式入口、依赖清单、画廊表 ID 与调用示例；Red Flags 新增 2 条（引用 V3 幽灵脚本 / 画廊落旧表、画廊同步失败静默放行）。

- **V5.16**: 修复 Archive 阶段 ZIP 文件块「无限 append」缺陷（说明文档堆积 8 个历史版本 ZIP）。
  - `register_skill.py` 的 ZIP 回挂链路由 append 改为**幂等替换**：新增 `list_doc_zip_file_blocks()`（走 `docs +fetch --doc-format xml --detail with-ids` 解析 `<figure><source>`，替代已失效的 `docx.v1.document_block.list` 内部代理）、`is_own_skill_zip()`（同名旧块识别，兼容 `_v1.2` / `-1.2` / ` (1)` 版本后缀变体）、`delete_doc_blocks()`（`block_delete` 批量删除）、`prune_stale_zip_blocks()`（编排 + 回读断言）。
  - 执行顺序锁定为「插新块 → `block_move_after` 归位 → 位置断言 → 再删同名旧块 → `sleep 2s` 回读断言唯一性」，确保新块落位成功后才删旧块，杜绝「删完插失败导致文档裸奔」。
  - 异物块（非本技能 ZIP）只报告 block_id + 文件名，**不自动删除**（删他人资产属破坏性操作，需人工拍板）；本流水线也绝不为其他技能往本文档插块。
  - 枚举/删除失败降级为「只插入不删除」+ 醒目 WARNING，不熔断整条流水线；同时修掉 `list_doc_file_blocks()` 在代理返回非 0 code 时静默返回空列表的隐患（改为 `raise`），避免清理动作静默变 no-op。
  - Red Flags 新增 3 条（只 append 不清理 / 未做数量==1 断言 / 自动删除异物块）；Verification 新增第 11 条「文件块唯一性断言」；Archive 章节新增「Archive 步骤文件块替换规则」。
- **V5.15**: 落地 DEC-20260821-001「决策录入必须双轨原子写入，单轨成功即判失败」到执行层（Layer 2）。
  - 新增 L3 断言层熔断脚本 `scripts/dual_track_atomic_write.py`：事务块绑定「飞书镜像写入 → 立刻本地 SSOT append」，写后 2s 执行 RAW read-after-write 双轨 ID 一致性断言（`assert_local_track` / `assert_mirror_track` / `assert_dual_track`），任一轨失败即 `raise` 熔断。
  - 失败即孤儿标记：自动写入死信队列 `.ephemeral_pool/orphan_decisions.jsonl`（`decision_id` / `failed_track` / `error` / `timestamp` / `suggested_fix`），标记 `⚠️[孤儿待修复]`。
  - 提供 `--dry-run`（零副作用前置校验）、`--verify-only <DEC-ID>`（事后巡检）与 `--inject-failure local|mirror`（故障注入自测）。
  - 复用 `tools/sync_decision_registry.py` 的鉴权与飞书读写链路，不重造轮子。
  - 新增独立章节「双轨原子写入约束 (Dual-Track Atomic Write)」；Common Rationalizations / Red Flags / Verification（新增第 10 条）/ Defaults 同步加固。
- **V5.14**: 修复 Post-Forge Git Push Hook 的 P1 级「假成功」缺陷（幽灵资产）。
  - `post_forge_git_push.sh` 由 `git push origin main` 改为 `git push origin HEAD:main`，不再依赖本地可能陈旧的 `main` ref（HEAD 处于 `aime/*` 特性分支时旧实现会推空、退出码仍为 0）。
  - **新增 push 结果的远端回读断言**：push 后回读 `git ls-remote origin refs/heads/main` 并与 `git rev-parse HEAD` 比对，SHA 不一致即以非 0 退出码熔断并输出醒目错误，杜绝仅凭退出码判定成功。
  - 新增 non-fast-forward 自愈：`fetch` → `rebase`（冲突回滚改 `merge`）→ 重试 push 一次；仍失败则非 0 退出并报告「需人工介入」。
  - 新增结构化审计日志（分支名 / 本地 HEAD SHA / 远端 main SHA / PASS-FAIL 断言结论）；无新增变更时也不再提前 `exit 0`，仍执行 push 与断言。
  - 新增 `POST_FORGE_DRY_RUN=1` 故障注入开关（跳过真实 push 但保留断言，用于验证失败链路），`SKIP_POST_FORGE_GIT_PUSH=1` 语义保持不变。
  - Red Flags 新增「仅凭 `git push` 退出码判定成功 / 未做远端 SHA 比对」；Verification 新增第 8 条「push 后远端 main SHA 必须等于本地 HEAD SHA」。
  - **附带修复**：ZIP 文件块回挂位置漂移。`register_skill.py` 的 `attach_zip_to_doc_via_mcp` 原先只调 `lark-cli docs +media-insert`（默认追加到文档末尾），导致 ZIP 挂在文档尾部而非标题下方；现新增 `move_block_to_doc_begin()`（`block_move_after` anchor = 文档 root token）与 `assert_zip_block_at_doc_begin()` 运行时断言，位置不符即 `raise`。
  - Red Flags / Verification 同步新增「文件块位置断言」条款（Verification 第 9 条）。
- **V5.13**: 正式写入 Git 自动归档 SOP 与自举约束。
  - 在 Archive 后新增「Git 自动归档」步骤，明确 hook 调用命令、GitHub 仓库、commit message 格式与失败汇报口径。
  - 在约束条件中固化每次 forge/upsert 后必须触发 Git push hook，且 `skill-forge-pipeline-v4` 自举迭代同样适用。
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
