---
name: skill-forge-pipeline
version: 5.26
description: 创建、升级、打包、发布、归档并上传到 Aime 云端的自制技能锻造流水线。适用于新技能锻造、既有技能迭代、技能上线发布、云端发布与台账归档场景。
---

# 技能锻造流水线 (Forge Pipeline V5.26)

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
- “git push 成功了就算发布完成，云端回头再点一下。”
- “upload 失败先给你本地路径就算交付。”
- “反正我知道要手动点『上传到云端』，这步跳过也行。”
- “`aime skill upload` 退出码是 0，就不用再 `aime skill list` 回读了。”
- “顺手加个 `--scope space` 让全员都能用，反正更方便。”
- “技能名带不带 v4 无所谓，改一半也能跑。”
- “说明文档正文标题里的版本号是给人看的，跟代码版本不一致也没啥影响。”
- “文档里没找到版本标识，打一句 warning 跳过就行。”
- “`v1.6.1` 就当 `1.6` 处理吧，patch 位没人在意。”
- “说明文档我全量重渲染一遍最省事，人工写的案例回头让他们再补。”
- “踩坑记录看着过时了，顺手清一清更整洁。”
- “这文档没有 Zone 锚点标题，那就按老规矩全量覆盖吧。”
- “Preserve Zone 我只是 update 了一下措辞，没删算保留吧。”
- “Changelog 我直接覆盖成最新一条，历史版本没人看。”
- “Zone 断言失败大概是接口抖动，重试不了就先跳过。”
- “Sheet 台账同步了就行，Wiki 那张表让人手动补。”
- “Wiki 同步反正不阻断，回读断言就顺手 return success 吧。”
- “Wiki 表没有版本列？那我加一列 / 塞进简介里就好了。”

## Red Flags（危险信号）

出现任意一条，必须熔断或要求用户确认（不得继续“假装成功”）：

- 没有执行 `CDA-Guardrails-Selfcheck`，就要进入打包/发布/归档。
- 升级技能只改了代码（`.py`）但没有同步修改说明书（`SKILL.md`）。
- 涉及“复盘报告 / 故障修复报告 / 架构演进报告 / 归档”类技能升级，但 `SKILL.md` 的 Workflow / SOP 中没有显式写入【文档生动化标准】。
- 涉及飞书资产写入/赋权/文件块挂载但没有 `include_secrets=true`。
- 输出中出现“应该/大概/可能/我猜/先跳过”，但没有可验证的 RAW 回读证据。
- ZIP 回挂只做 append 不清理同名旧块，或只验证「文件块存在」而不验证「出现次数 == 1」。
- ZIP 文件块唯一性断言失败后，只打印 ⚠️ WARNING 就继续走 metadata 落盘 / 台账写入 / 宣称发布成功。
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
- **Git push 断言 PASS 之后没有执行 `aime skill upload`，就宣称「发布完成」** —— 技能仍是本地草稿，用户还得人工点「上传到云端」。
- **仅凭 `aime skill upload` 的退出码判定成功**，没有 `aime skill list` 云端回读证据。
- 云端上传失败被静默成 WARNING / 直接跳过，既没标记「需手动上传」，也没落死信队列。
- 默认给 `aime skill upload` 加了 `--scope space` 或 `--enable-by-default=true`（用户未显式要求就擅自扩大可见范围）。
- upload 撞权限墙后擅自切换空间或反复重试绕过，而不是如实报告「需要项目空间管理员加成员」。
- Cloud Publish 在 Git Push 之前执行，或 git push 断言 FAIL 后仍继续上云。
- 技能改名只改了目录/`SKILL.md`，漏改脚本内硬编码路径或跨技能路由引用（造成断链）。
- **说明文档正文/标题版本号仍是旧版（如 V5.19），却宣称版本已同步** —— 没有做正文版本回读断言。
- 文档版本同步链路走到「未找到版本标识 → 打 WARNING → skip」的静默分支（必须改为 `raise`）。
- 版本号归一化时丢掉 patch 位（`v1.6.1` → `1.6`），导致三段版本被静默降级。
- **对飞书说明文档执行「全量覆盖」或「整篇重渲染」** —— 会抹平 Preserve Zone 的人工沉淀（使用案例 / 踩坑 / 注意事项）。
- 对 Preserve Zone 内的 block 执行任何 `block_delete` / `block_replace` / `str_replace`。
- 更新 Changelog 时采用覆盖而非追加，导致历史版本条目丢失。
- 老文档缺失 Zone 锚点标题时，**猜测**边界并照旧覆盖，而不是安全降级（末尾补建锚点 + 显式告知）。
- 三分区写入后没有 RAW 回读断言（锚点各 1 次 + Preserve 正文存在性），或断言失败后降级为 WARNING 继续。
- 写入前没有先 `docs +fetch --detail with-ids` 读取真实结构，就直接下发 block 级写指令。
- 改文档标题仍走 `docs +update --command str_replace --doc-format markdown`（剥 `<title>` 标签后当正文下发，会在正文物化同名 h1，复现「双大标题」）。
- `assert_no_phantom_h1()` 检测到与 title 同名的正文 h1，却只打 WARNING 不删除、不熔断，或因 fetch 抖动静默 `return success` 而不标记 `degraded`。
- forge 只同步了「专属技能清单」Sheet，却没有同步 Wiki「技能存量清单」表格（Wiki 长期腐化、覆盖率下滑的历史根因）。
- Wiki 存量清单同步**内部**的写后回读断言失败（行数不符 / 技能名出现次数 != 1），却被包装成 success 上报。
- Wiki 存量清单 upsert 未以「技能名称」为主键，导致同一技能重复 forge 追加出重复行。
- 为了写版本号擅自给 Wiki 存量清单表增列，或覆盖人工撰写的「简介」列文案。

## Verification（强制验收清单）

当你宣称“流水线完成”时，必须同时满足：

1. **CDA 自检通过**：`scripts/cda_guardrails_selfcheck.py` 退出码为 0，并清晰输出风险等级与三层覆盖情况。
2. **双轨校验通过**：升级技能时，`SKILL.md` 与底层代码（如 `.py`）必须同时有变更（否则立刻熔断）。
3. **Zip 发布闭环**：`scripts/register_skill.py` 生成的 `metadata.json` 中必须包含 `zip_path`、`drive_file_url`、`doc_link`、`wiki_url`、`wiki_node_token`。
4. **说明文档回挂验收（UPSERT 唯一性断言）**：回捞下载最新文档，确认标题下方存在最新 zip 的原生 File Block（非纯文本链接），**且本技能 ZIP 文件块在文档中出现次数必须严格 == 1**。「存在即通过」的旧口径已废弃——它正是幽灵安装包长期堆积（info-miner 曾堆到 14 个）而无人发现的根因。枚举失败 / 删除失败 / 回读失败 / 数量 != 1 四种情况**一律 `raise` 熔断**，严禁降级为 WARNING 后继续宣称发布成功。
5. **Wiki 归档验收**：说明文档必须已成功迁入目标 Wiki 节点；若 Wiki Mount Phase 失败，发布流程必须立刻熔断，不得继续落盘 `metadata.json` 或宣称发布成功。
6. **归档台账验收**：对【专属技能清单】写入必须走 RAW 原子锁（写→等 2s→读回核对），不一致立刻熔断。
7. **生动化标准验收**：若目标技能属于报告生成、修复总结、架构演进或归档类能力，`SKILL.md` 中必须存在可执行的【文档生动化标准】条款，并明确联动 `cyber-inspiration-generator` 与“头部前置嵌入”要求。
8. **云盘 ZIP 赋权验收**：Archive 阶段的 ZIP 赋权必须输出 `lark-cli drive +member-list` RAW 回读证据（目标 open_id/owner_id + `perm == full_access`）。赋权失败必须熔断，禁止以 WARNING 形式放行。

9. **Git 同步远端断言验收**：Post-Forge Git Push 之后，远端 `origin/main` 的 commit SHA **必须严格等于**本地 `git rev-parse HEAD`（通过 `git ls-remote origin refs/heads/main` 回读比对）。只要不一致，即判定 push 未生效，hook 必须以非 0 退出码熔断，禁止宣称「已 push 到 qi-skills」。
10. **文件块位置断言验收**：ZIP 原生 File Block 必须位于说明文档**第一个正文块**（BLOCK_BEGIN，标题正下方）。`register_skill.py` 在 `+media-insert` 之后必须执行 `block_move_after`（anchor = 文档 root token）归位，并回读文档 XML 断言首个正文块 id == 新建文件块 id；不一致立刻 `raise` 熔断。
11. **双轨原子写入验收**：凡涉及「决策台账写入飞书镜像」的节点，本地 SSOT `memory/topics/decision-registry.md` 末条决策 ID 与飞书镜像末行 ID **必须一致**，且必须输出双轨回读证据（`assert_local_track` / `assert_mirror_track` 的 evidence）。任一轨失败即 `raise` 熔断并落孤儿死信队列，禁止宣称完成。
12. **文件块唯一性断言**：Archive 阶段回挂 ZIP 后，必须回读说明文档并断言「属于本技能的 ZIP 文件块数量恰好为 1」且其 block_id/file_token 等于本次新块。不满足时必须显式输出残留清单与人工解法（允许非熔断，禁止静默）。异物块（其他技能的 ZIP）必须列出 block_id + 文件名交由人工拍板，严禁自动删除。
13. **云端发布验收（V5.19 新增）**：Git push 断言 PASS 之后，必须完成云端发布三件套且全部有据可查：
    - ① `aime skill upload <技能绝对路径>` 退出码为 0；
    - ② **云端回读断言 PASS**：`aime -o json skill list` 中出现该技能名且 `ID` 非空，`aime -o json skill draft list` 的 `cloudVersionTime > 0`（或该名已不在草稿列表），且云端 `UpdatedAt` 相对 upload 前基线有推进；
    - ③ `SKILL.md` 的「## ☁️ 云端发布记录」小节与 `metadata.json` 均记录 `cloud_publish_status` / `cloud_scope` / `cloud_published_at`。
    仅凭 upload 退出码宣称成功视为 P1 假成功缺陷。上传失败必须标记「需手动上传」+ 落死信队列 + 输出醒目 ERROR，禁止静默跳过。
14. **说明文档正文版本回读断言验收（V5.20 新增）**：SSOT 版本写回 `SKILL.md` 之后，必须调用 `assert_doc_body_version_synced(doc_url, new_version)`：重新下载说明文档 → 提取**标题内嵌版本**（`(... Vx.y[.z])`）与**带标签版本**（`version: x.y` / `版本号：x.y` / `` `version`: `x.y` ``）→ 断言全部等于本次锻造版本。任一处仍为旧版、或全文找不到任何版本标识，都必须 `raise GuardrailViolation` 并标记 **【文档版本未同步】**，禁止静默成功。该断言执行两次：写入后（sleep 2s）+ Wiki Mount 之后（防止搬家把旧版本带回）。
    ⚠️ 断言口径不得使用 `isDraft == False`：真机验证表明只要本地存在同名草稿目录，`skill list` 就会把记录标成 `isDraft=True`，主站点 upload 后也不会丢弃本地草稿，用它断言会误熔断。

15. **飞书说明文档三分区验收（V5.23 新增）**：任何对飞书技能说明文档的写入/更新，必须按 Zone 分区执行且留下回读证据：
    - ① **写前读真实结构**：先 `lark-cli docs +fetch --doc-format xml --detail with-ids` 拿到带 block id 的结构，再决定写法；禁止盲写。
    - ② **Overwrite Zone**（头部版本信息框 / 触发词 / 接口契约）从 `SKILL.md` 重新渲染覆盖；每个待删 block 必须先经 `ZoneMap.zone_of()` 断言归属 Overwrite Zone，否则 `raise`。
    - ③ **Preserve Zone**（使用案例 / 踩坑记录 / 注意事项 / 人工补充背景）**一律不 update、不 delete**。
    - ④ **Append Zone**（更新日志）只在末尾追加本版本条目，禁止覆盖历史条目。
    - ⑤ **RAW 回读断言**：两个锚点标题各出现**恰好 1 次**；写前采样的 Preserve Zone 正文在回读结果中**仍然存在**。任一不满足即 `raise GuardrailViolation`，禁止静默 WARNING。
    - ⑥ 老文档无锚点时必须**安全降级**（末尾补建锚点章节 + 日志显式告知 `[ZONE-DEGRADED]`），绝不误删既有正文。

16. **Wiki 技能存量清单 Upsert 验收（V5.24 新增）**：Sheet 台账写入完成后必须调用 `sync_wiki_skill_list()`（`scripts/wiki_skill_list_sync.py`）：以**技能名称**为主键 upsert Wiki「一、技能存量清单 (Skill Registry)」表格 → `block_replace` 整表 → `sleep 2s` → `docs +fetch --doc-format markdown` 回读断言（行数 == 预期、目标技能名在表格行中**恰好出现 1 次**）。断言失败必须 `raise WikiSyncError`；调用侧允许把该步骤降级为 `⚠️ WARNING: Wiki sync failed: <原因>` 并继续 forge（Wiki 同步是增强项），但**禁止**把断言失败伪装成成功。表格 block id 每次 `block_replace` 后都会变化，必须动态解析，禁止硬编码。

17. **文档标题改写路径与幽灵 h1 断言验收（V5.26 新增）**：说明文档标题的改写**必须**走 `lark-cli drive +update-title`（`update_doc_title_via_drive_api()`），严禁再经 `docs +update --command str_replace --doc-format markdown` 下发标题文案。`sync_version_to_skill_doc_via_mcp()` 末尾必须调用 `assert_no_phantom_h1(doc_url, doc_title)`：在 Overwrite Zone（Preserve 锚点之前）范围内查找与文档 title 同名（空白归一化）的 h1 block，命中即 `block_delete` 自动纠正并打印 `⚠️ [L3-autocorrect] deleted phantom h1: <block_id>`，删后 sleep 2s 回读断言 count == 0，仍存在即 `raise GuardrailViolation`。fetch 失败只允许降级为醒目 WARNING 且必须在返回值标记 `phantom_h1_check="degraded"`，禁止静默成功。

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
cd user_skills/skill-forge-pipeline
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

- **正式入口（唯一）**：`user_skills/skill-forge-pipeline/scripts/celebrate_skill.py`。该脚本在启动前执行**依赖存在性断言**，任一依赖缺失即 `raise` 熔断；画廊同步失败同样 `raise`，**禁止**再出现 "proceeding to ensure workflow continuity" 一类静默放行。
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
python3 user_skills/skill-forge-pipeline/scripts/celebrate_skill.py \
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
- 在归档执行时，必须完成版本号升迁（Major +1.0 / Minor +0.1 / Patch +0.0.1），并将新版本号 **回写覆盖** 本地目标技能 `SKILL.md`。三段版本（`X.Y.Z`）的 **patch 位必须原样保留**，禁止归一化成两段（V5.20 修复）。
- 同时必须通过 `bytedcli-auth` + MCP `lark_sheets_update`，对飞书台账【专属技能清单】的【版本号】列做定向覆写，并执行“写 → 等 2s → 读回核对”的 RAW 级验收。
- **说明文档正文版本强同步 + L3 回读断言（V5.20，替代原 best-effort 口径）**：不再是「有则改、无则跳过」。
  1. **改写范围**：标题内嵌版本（`# ... (Forge Pipeline V5.20)`）与带标签版本（`version: 5.20` / `版本号：v5.20` / `` - `version`: `5.20` ``）**全部**改写；Changelog 历史行（如 `- 2026-04-27：v5.2.0`）刻意不匹配，保持记录保真。
  2. **回读断言**：写入后 `sleep 2s` 重新下载文档，断言上述所有版本标识 == 本次锻造版本，不通过即 `raise GuardrailViolation`，错误信息带 **【文档版本未同步】** 标记。
  3. **禁止静默跳过**：文档全文找不到任何版本标识时，同样 `raise`（原实现只打 `⚠️ ... skip SSOT doc sync` 就放行，是本轮堵死的漏洞）。
  4. **二次断言**：Wiki Mount 完成后再执行一次 `assert_doc_body_version_synced(final_doc_link, ssot_version)`，结果落 `metadata.json` 的 `doc_version_synced` / `doc_version_sync`。
  5. **历史根因（三重）**：① 旧正则只认「带标签」版本，认不出标题里的 `V5.19`；② 替换串误写成 `r"\\1"`（字面反斜杠+1，而非分组反向引用）；③ `.lark.md` 兜底下载不含 `<!-- BLOCK_n -->` 标记，导致按块遍历的循环永远进不了替换分支。三者叠加 = 连续两轮「假成功」。

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
- **Wiki 技能存量清单 Upsert（V5.24 新增）**：Sheet 台账写入完成之后、Celebrate 之前，`register_skill.py` 必须调用 `run_wiki_skill_list_sync()` → `scripts/wiki_skill_list_sync.py::sync_wiki_skill_list()`，把本次 forge 的技能 upsert 进 Wiki 页面（默认 `--wiki-registry-url` = Aime 技能库首页）的「一、技能存量清单 (Skill Registry)」6 列表格。
  - **主键 = 技能名称列**（精确匹配，去空白）。已存在 → 只更新「访问链接」（若本次有说明文档 URL）与「归档日期」（本次 forge 日期）；不存在 → tbody 末尾追加一行，序号 = 现有最大序号 + 1，缺链接填 `⚠️[待补链接]`，使用次数填 `-`。
  - **不破坏现有列结构为最高优先级**：现表无独立版本列，故**不写版本号、不增列、不覆盖人工撰写的「简介」列**（版本号权威载体是 `SKILL.md` frontmatter + 专属技能清单 Sheet 的【版本号】列）。若未来表头新增「版本号」列，脚本会自动识别并写入。
  - **执行链路**：`docs +fetch --detail with-ids` 读真实结构（禁止盲写）→ 解析表格（block id 动态解析）→ 按主键 upsert → 重建整表 XML（不带 id）→ `block_replace` → `sleep 2s` → markdown 回读断言。
  - **幂等**：同一技能重复 forge 只更新原行；解析到重复行会直接熔断，要求人工先去重。
  - **失败边界**：整步用 `try/except` 包裹，失败打印 `⚠️ WARNING: Wiki sync failed: <原因>` 后继续 forge 主流程；`--skip-wiki-sync` 可显式跳过。内部回读断言失败**必须**让该步判定为 failed（写入 `metadata` 的 `wiki_registry_sync_status`），不得假装成功。
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

### 5. Cloud Publish 云端发布（V5.19 新增）

Git Push 断言 PASS 之后，流水线必须继续把技能推上 Aime 云端。此前技能虽已进 GitHub，却仍停留在 Aime 本地草稿，需要人工去界面点「上传到云端」——这是 V5.19 要消灭的最后一段手工环节。

**唯一入口**：`scripts/cloud_publish.py`（由 `register_skill.py` 在 Git Push 成功后自动调用，也可手动重跑）。

```bash
# 自动链路（register_skill.py 内部调用，无需手动）
# 手动补跑 / 重试：
python3 user_skills/skill-forge-pipeline/scripts/cloud_publish.py \
  --skill-dir "user_skills/skill-forge-pipeline" \
  --version "5.20" \
  --cloud-scope user

# 零副作用预演
python3 user_skills/skill-forge-pipeline/scripts/cloud_publish.py \
  --skill-dir "user_skills/skill-forge-pipeline" --dry-run
```

执行契约（顺序不可颠倒）：

1. **前置校验（L3）**：`validate_cloud_publish_args()` 断言技能目录存在、含 `SKILL.md`、`--cloud-scope ∈ {user, space}`；`--enable-by-default` 仅在 `space` 下有意义，`user` 下传入即报错。
2. **基线快照**：`aime -o json skill list` + `aime -o json skill draft list` 取 upload 前的 `UpdatedAt` / `cloudVersionTime` 基线，供事后推进比对。
3. **草稿前置**：若技能不在 `aime skill draft list` 中，先执行 `aime skill draft create <技能绝对路径>`，再 upload。
4. **上传**：唯一合法命令 `aime skill upload <技能绝对路径>`（必须传**绝对路径**），附 `--scope <cloud-scope>`；只有 `space` 才附 `--enable-by-default`。
5. **云端回读断言（核心护栏）**：`assert_cloud_skill_present()` 重新拉取云端列表与草稿列表，要求：云端存在同名技能且 `ID` 非空；`cloudVersionTime > 0`（或该名已不在草稿列表）；云端 `UpdatedAt` 相对基线有推进。任一不满足即判 upload 未生效。
6. **成功记录**：把 `cloud_publish_status=success` / `cloud_scope` / `cloud_published_at` / `cloud_skill_id` 写入 `SKILL.md` 的「## ☁️ 云端发布记录」小节（幂等覆盖，不重复堆叠）与 `metadata.json`。
7. **失败处理（禁止静默）**：输出醒目 `ERROR`；在 `SKILL.md` 云端发布记录中标记 **`⚠️ 需手动上传`**；写死信队列 `.ephemeral_pool/cloud_publish_failures.jsonl`（含 `skill_name` / `version` / `stage` / `error` / `timestamp` / `manual_command`）；`metadata.json` 落 `cloud_publish_status=failed` + `cloud_publish_error`。
8. **权限墙不得绕行**：若 upload 因空间权限被拒，**严禁自动切换 scope / 换空间重试**。必须提示用户「联系项目空间管理员将你加为成员」，并按第 7 条标记为需手动上传。
9. **调试开关**：`SKIP_CLOUD_PUBLISH=1` 显式跳过整个云端发布并以 0 退出（状态记为 `skipped`）。
10. **draft-discard 自愈（真机血泪，V5.19 自举中真实发生 3 次）**：`aime skill upload` 成功后会打印 `Discarding local draft "<name>"`，并**按技能名**清理 workspace 草稿 —— 真实目录 `user_skills/<name>/` 会被连带删除，且随后 workspace 可能从云端回填**旧版本**同名/旧名目录，等于把你刚写完的新版本工作副本抹掉。因此：
    - `cloud_publish.py` 在 upload 前对技能目录做完整备份，upload 后若目录消失则**自动原地复原**（`self-heal` 日志），备份失败必须显式告警；
    - 从暂存副本上传**不能**规避该行为（discard 认名不认路径），别把它当解法；
    - `record_cloud_publish_in_skill_md()` 遇到 `SKILL.md` 已被清理时只告警不 `raise` —— 云端确已发布成功，不能因回写失败把成功反转成崩溃；
    - 兜底恢复命令：`git restore --source=HEAD -- user_skills/<name>`。
11. **Disabled 显式提示**：云端回读若发现 `Disabled=True`，说明「上传成功但技能未启用」，必须显式提示执行 `aime skill enable <name>`，不得当作已生效。

⚠️ **断言口径警告**：不要用 `isDraft == False` 判定上传成功。真机验证表明，只要本地仍存在同名草稿目录，`aime skill list` 里的云端记录依然是 `isDraft=True`；upload 也不会删掉本地草稿。用它断言会造成误熔断。

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
- **自举同频**：forge 自举（对 `skill-forge-pipeline` 自身迭代）时同样需要触发 Git push，并同样接受远端 SHA 回读断言。
- **反假成功铁律（No Fake Success）**：任何“同步/写入/发布”类副作用，都必须有**独立回读证据**（Git 走远端 SHA 比对，飞书走 RAW 回读，云端走 `aime skill list` 回读）。只看命令退出码即宣称成功，视为 P1 缺陷。
- **云端发布强制触发（V5.19）**：Git push 断言 PASS 后必须继续执行 Cloud Publish；未设置 `SKIP_CLOUD_PUBLISH=1` 却跳过，视为发布链路未完成。
- **云端 scope 保守原则**：默认 `--scope user`。要写 `space` 或开 `--enable-by-default` 必须由用户显式指令，Agent 不得自行升级作用域。

## 合规默认值（Defaults）

- `--user-email` 默认：`yuqinan@bytedance.com`（ZIP 资产访问修复默认目标用户；经 MCP personal-space 链路恢复可管理权限）
- 文档挂载默认插入点：`BLOCK_BEGIN`（标题正下方）
- `--wiki-node-token` 默认：`GU0ewkyaGi4i5nkwBtNcM3aPn9g`（Aime 技能库根节点）
- `--wiki-registry-url` 默认：`https://bytedance.larkoffice.com/wiki/GU0ewkyaGi4i5nkwBtNcM3aPn9g`（Wiki 技能存量清单表所在页面）
- Wiki 存量清单同步：默认开启（`--skip-wiki-sync` 才跳过）；失败降级为 WARNING，不阻断 forge
- Wiki 存量清单 upsert 主键默认：技能名称列；缺链接占位符 `⚠️[待补链接]`，使用次数占位符 `-`
- 写后即读 RAW 校验：默认开启（任何不一致必须熔断）
- 文档标题改写通道默认：`lark-cli drive +update-title`（禁用 `docs +update --command str_replace` 改标题）
- 幽灵 h1 断言（`assert_no_phantom_h1`）：默认开启，检测到即自动删除 + 回读断言 count == 0
- 说明文档正文版本回读断言：默认开启（`--skip-ssot-doc-sync` 才跳过，仅限调试）
- 版本号形态：保留来源形态（两段进两段出、三段进三段出，patch 位不得截断）；`--bump` 支持 `major|minor|patch`
- **`--initial-version` 默认：`1.1`**（首次发布起始版本号）
  - 当 `SKILL.md` 当前版本仍处于 `0.x` 脚手架阶段时，流水线判定为「首次发布」，**会忽略 `--bump`，直接将版本设为 `1.1`**，不再做 `0.x → 0.x+0.1` 的小迭代。
  - 已经 ≥ `1.0` 的技能，按原 `--bump major|minor` 规则升迁，不受影响。
  - 如需自定义首发版本，可显式传 `--initial-version 2.0` 覆盖默认；如需强制指定任意目标版本，可显式传 `--new-version 0.2`。
- 决策镜像台账默认：`https://bytedance.larkoffice.com/wiki/PnnDwYr13imUyVkVPshc46ICnVh`
- 本地 SSOT 默认路径：`memory/topics/decision-registry.md`
- 孤儿死信队列默认路径：`.ephemeral_pool/orphan_decisions.jsonl`
- 双轨 RAW 回读等待默认：`2` 秒（写 → 等 2s → 双轨回读）
- **`--cloud-scope` 默认：`user`**（个人可见；**禁止**默认 `space`，避免未经确认就影响整个项目空间）
- **`--enable-by-default` 默认：`false`**（且仅在 `--cloud-scope space` 下有意义，`user` 下传入即报错）
- 云端发布命令默认：`aime skill upload <技能绝对路径>`（唯一合法上传命令）
- 云端回读断言默认：`aime -o json skill list` + `aime -o json skill draft list`，默认开启，失败即判 upload 未生效
- 云端发布死信队列默认：`.ephemeral_pool/cloud_publish_failures.jsonl`
- 云端发布记录承载默认：`SKILL.md` 的「## ☁️ 云端发布记录」小节 + `metadata.json`
- 云端发布调试开关默认：`SKIP_CLOUD_PUBLISH=1`（未设置即必须执行）

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
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py \
  --dry-run --decision-id DEC-20260821-001 --entry-file /tmp/dec_entry.yaml

# 双轨原子写入（镜像写入 -> 立刻本地 append -> 双轨断言）
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py \
  --decision-id DEC-20260821-001 --entry-file /tmp/dec_entry.yaml

# 事后巡检：只做双轨回读断言
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py \
  --verify-only DEC-20260821-001

# 故障注入自测：人为让某一轨失败，验证 raise + 死信队列链路
python3 user_skills/skill-forge-pipeline/scripts/dual_track_atomic_write.py \
  --verify-only DEC-20260821-001 --inject-failure mirror
```

> 所有调用必须设置 `include_secrets=true`；飞书读写一律走 MCP / `lark-cli` 链路，严禁裸调 OpenAPI。

## 飞书说明文档三分区策略 (Doc Zone Strategy) — V5.23

### 为什么要分区

forge 每次发布都会更新飞书技能说明文档。V5.22 之前只有两种形态：**全量覆盖**或**纯 append**，两者都缺失「哪些区域可覆盖、哪些必须保留」的语义：

- 全量覆盖 → 人工写的使用案例 / 踩坑 / 注意事项被机器抹平，沉淀资产永久丢失；
- 纯 append → 版本号、触发词、接口契约永远堆叠旧版，读者分不清哪份是现行版本。

**核心设计原则（两套事实来源，各管一段）**：

- **飞书文档是「对人」的**：使用案例、踩坑记录、注意事项、人工补充背景是**人写的沉淀资产**，forge 不得覆盖。
- **`SKILL.md` 是「对机器」的 SSOT**：版本号、描述、触发词、接口契约由 `SKILL.md` 渲染，飞书文档对应章节可被安全覆盖。

### Zone 定义

| Zone | 内容 | forge 行为 |
|---|---|---|
| **Overwrite Zone** | 头部版本信息高亮框（版本号 / 描述 / 更新时间）、触发词章节、接口契约 / 参数说明 | 每次 forge 从 `SKILL.md` 重新渲染并覆盖对应 block |
| **Preserve Zone** | 使用案例、踩坑记录、注意事项、人工补充背景 | **不 update / 不 delete**，云端原内容原样保留 |
| **Append Zone** | 更新日志 Changelog / 版本历史 | 末尾**追加**新版本条目，不覆盖旧条目 |

### Zone 边界锚点（固定标题，不可随意改动）

- Overwrite Zone 结束 / Preserve Zone 开始：`## 📝 使用案例 & 踩坑记录`
- Preserve Zone 结束 / Append Zone 开始：`## 📋 更新日志`

```
<文档开头> ... Overwrite Zone ...
## 📝 使用案例 & 踩坑记录      <- Preserve Zone 开始
... Preserve Zone ...
## 📋 更新日志                <- Append Zone 开始
... Append Zone ... <文档结尾>
```

### 执行契约（`scripts/doc_zone_manager.py`）

唯一入口 `sync_doc_zones()`，由 `register_skill.py` 在「版本标识同步之后、Wiki Mount 之前」自动调用。顺序不可颠倒：

1. **读真实结构**：`fetch_zone_map()` → `lark-cli docs +fetch --doc-format xml --detail with-ids`，解析成有序顶层 block 列表（`<ul>`/`<ol>` 自身无 id，按 `<li>` 展开）。**禁止盲写**。
2. **采样 Preserve Zone**：`ZoneMap.preserve_samples()` 取最多 8 条人工正文，作为写后存在性断言的基准。
3. **补建缺失锚点（安全降级）**：`ensure_zone_anchors()` 只做 `append`，绝不 delete / 不重排既有正文，并打印 `[ZONE-DEGRADED]` 显式告知。补建后重扫时，断言样本必须取**补建前 ∪ 补建后的并集**，禁止用重扫结果覆盖原样本（否则存在性断言退化为自证）。
4. **覆盖 Overwrite Zone**：`update_overwrite_zone()` 按 h2 章节整段重建；**每个待删 block 都必须先经 `ZoneMap.zone_of()` 断言归属 Overwrite Zone**，否则 `raise` —— 这是防止误伤 Preserve Zone 的最后一道闸门。
5. **追加 Changelog**：`append_changelog_entry()` + `build_changelog_entry_from_skill_md()`（文案取自 `SKILL.md` 更新日志，SSOT 原则）。
6. **等 2s → RAW 回读断言**：`assert_zone_integrity()`。

### 零信任断言（L3 熔断）

`assert_zone_integrity()` 必须同时满足，否则 `raise GuardrailViolation`：

1. 两个锚点标题在文档中**各出现恰好 1 次**（多出 = 重复补建，缺失 = 误删）；
2. 写前采样的 Preserve Zone 正文在回读结果中**仍然存在**（存在性断言，空白归一化后比对）。

**禁止**降级为 WARNING 后继续宣称成功。

### 老文档兼容（安全降级）

存量文档没有锚点标题时，**绝不猜测边界、绝不删除既有正文**：`resolve_zones()` 会把整篇标记为不可动的 Preserve Zone（`overwrite` 为空），仅在末尾补建缺失锚点章节（Preserve Zone 写入占位提示 `[待补充使用案例]`），并在日志与 `.forge_receipt.json` 的 `doc_zone_degraded` 字段中显式记录降级原因。锚点**重复**或**顺序颠倒**同样视为边界不可信 → 降级且不改写 Overwrite Zone（重复锚点属人工介入范畴，不自动删除）。

### 调用示例

```bash
# 只读：打印三个 Zone 的边界划分（零副作用，排查降级原因首选）
python3 scripts/doc_zone_manager.py --doc "<doc_url>" --skill-dir . --dry-run

# 事后巡检：只做三分区回读断言
python3 scripts/doc_zone_manager.py --doc "<doc_url>" --skill-dir . --verify-only

# 手动补跑三分区同步
python3 scripts/doc_zone_manager.py --doc "<doc_url>" --skill-dir . \
  --version "5.23" --changelog-entry "- **V5.23**：新增三分区策略。"

# 新建文档：先产出带 Zone 锚点的骨架，再交给 `lark-cli docs +create` 导入
python3 scripts/register_skill.py --name x --desc y --path z \
  --skill-dir "user_skills/<skill>" --emit-new-doc-markdown /tmp/skeleton.md

# 离线自检（纯函数，不触网）
python3 scripts/test_doc_zones.py
```

> 调试开关：`--skip-doc-zones`（正式发布默认必须执行，它同时承担 Preserve Zone 的保护断言）。

## 更新日志 (Changelog)

- **V5.26**: 根治「双大标题」复现的 P2 级残留缺陷（标题改写路径错位）。
  - **根因**：`register_skill.py::sync_version_to_skill_doc_via_mcp()` 改文档标题时，把 `<title>...</title>` 剥掉标签后走 `lark-cli docs +update --command str_replace --doc-format markdown` 下发。V5.25 已删除写死的正文 h1，于是这条 markdown str_replace 在正文找不到目标文本时**重新物化了一个同名 h1 block**，「双大标题」每次版本号变化都会复发（手工删除只是治标）。
  - **Plan A（主修复）**：新增 `update_doc_title_via_drive_api(doc_url, new_title)`，标题改写改走独立重命名 API `lark-cli drive +update-title --as user --url <docx_url> --title <新标题> --format json`（只改文档元数据，不触碰正文；wiki 节点标题自动同步；注意 99991400 限流，禁止并行批量）。正文各行（labeled version / 正文 heading）仍走原 `str_replace` 路径不变。原「先改正文、最后改 title 以规避 degrade_code=1014 ambiguous」的顺序契约不再必需（注释已更新为「title 已走独立 API，不再有 ambiguous 风险」），顺序保留仅作历史习惯。
  - **Plan B（收尾兜底断言，双保险）**：新增 `assert_no_phantom_h1(doc_url, doc_title)` —— `docs +fetch --doc-format xml --detail with-ids` 读带 id 结构（复用 `doc_zone_manager.sanitize_doc_xml()` 处理未转义裸 `&`），在 Overwrite Zone（Preserve 锚点 `## 📝 使用案例 & 踩坑记录` 之前）范围内查找与文档 title 同名（空白归一化）的 h1 block；命中即 `block_delete` 自动纠正 + 打印 `⚠️ [L3-autocorrect] deleted phantom h1: <block_id>` + sleep 2s 回读断言 count == 0，仍存在即 `raise GuardrailViolation`。fetch 抖动只允许降级为醒目 WARNING 并标记 `phantom_h1_check="degraded"`，禁止静默 return success。该断言在 `assert_doc_body_version_synced()` 之后调用，结果并入返回 dict（`phantom_h1_check` / `phantom_h1_removed`）。
  - CDA L1：Red Flags 新增 2 条（标题走 markdown str_replace / 幽灵 h1 只 WARNING 不熔断）；Verification 新增第 17 条「文档标题改写路径与幽灵 h1 断言验收」；Defaults 新增标题改写通道与幽灵 h1 断言默认值。

- **V5.25**: 根治说明文档「双大标题」冗余，并强化三个 Zone 的入口引导语。
  - **根因**：`doc_zone_manager.py::build_new_doc_markdown()` 的新建文档骨架第一行写死 `# 【技能说明】<name> (V<version>)`，而飞书文档原生 `title` 已承载同一标题 —— 于是文档顶部出现两个一模一样的大标题（本轮 forge 说明文档实测到冗余 h1 `doxcn9YTJXtImUhzmRHmBQPFaEg`）。Overwrite Zone 的职责只应是「高亮框 / 版本信息 / 触发词 / 接口契约」，标题不属于它。
  - **修复**：`build_new_doc_markdown()` 删除 h1 行（保留显式 NOTE 注释说明原因），文档骨架自出生起不再产生重复标题；`update_overwrite_zone()` 本就不渲染 h1，无需改动（已复核确认）。
  - **Zone 引导语强化**：`PRESERVE_HINT` 改为 `💡 此区域为人工沉淀区（Preserve Zone），forge 不会覆盖，请在此记录使用案例、踩坑与注意事项。`；新增 `APPEND_HINT` = `📌 此区域为更新日志区（Append Zone），forge 每次发布后自动追加，请勿手动修改已有条目。`，并在 `ensure_zone_anchors()`（老文档补建）与 `build_new_doc_markdown()`（新建骨架）两条路径统一引用，杜绝两处提示语各写一套的漂移。
  - **配套治标**：手工清除存量 forge 说明文档中的冗余 h1 块，RAW 回读断言正文中该标题文本出现次数 == 0（title 不计入正文 block）。
  - 回归：`scripts/test_doc_zones.py` 25 例全绿。

- **V5.24**: 新增 Wiki「技能存量清单」Upsert 钩子，补齐 forge 台账同步的第二条轨道。
  - **根因**：forge 长期只同步「专属技能清单」Sheet，Wiki 上给人扫读的「一、技能存量清单 (Skill Registry)」表格无人维护，导致 Wiki 三个月未更新、覆盖率一度只有 31.4%。
  - 新增 `scripts/wiki_skill_list_sync.py`：`sync_wiki_skill_list()` 为唯一编排入口，链路为「`docs +fetch --detail with-ids` 读真实结构 → `locate_registry_table()` 动态解析表格 block id（每次 `block_replace` 后都会变，禁止硬编码）→ `_upsert_rows()` 按**技能名称**主键 upsert → `render_table_xml()` 重建整表（不带 id）→ `block_replace` → sleep 2s → `assert_wiki_registry_synced()` markdown 回读断言」。
  - 断言口径：行数 == 预期 + 目标技能名在表格行中**恰好出现 1 次**；不满足即 `raise WikiSyncError`。解析到同名重复行同样熔断（要求人工先去重），保证幂等。
  - 版本号取舍：现表固定 6 列且无版本列，为「不破坏现有 51 行结构」，选择**不写版本号 / 不增列 / 不覆盖人工「简介」文案**（版本号权威载体是 `SKILL.md` frontmatter + Sheet 的【版本号】列）；未来若表头出现「版本号」列则自动写入。
  - `register_skill.py`：新增 `run_wiki_skill_list_sync()`（Sheet 台账写入之后、Celebrate 之前调用）、`--wiki-registry-url` 与 `--skip-wiki-sync` 开关；结果落 `.forge_receipt.json` 的 `wiki_registry_sync_status` / `wiki_registry_sync`。
  - 失败边界：Wiki 同步是增强项，失败打印 `⚠️ WARNING: Wiki sync failed: <原因>` 后继续 forge 主流程；但同步**内部**的回读断言失败必须判定该步为 failed，禁止伪装成功。
  - 新增 `scripts/test_wiki_skill_list_sync.py` 离线自检（21 例全绿）：覆盖表格定位、主键更新、幂等二次 forge、序号递增、占位符、重复行熔断、`&` 转义、缺标题熔断。

- **V5.23**: 新增「飞书说明文档三分区（Zone）策略」，终结 forge 覆盖人工沉淀的风险。
  - **根因**：说明文档写入逻辑此前只有「全量覆盖」或「纯 append」两种形态，没有区分可覆盖区与人工沉淀区。全量覆盖会抹平人工写的使用案例 / 踩坑 / 注意事项；纯 append 又让版本号、触发词、接口契约堆叠旧版无人收敛。
  - **设计原则**：飞书文档是「对人」的（人工沉淀不可覆盖）；`SKILL.md` 是「对机器」的 SSOT（版本 / 描述 / 触发词 / 接口契约由它渲染，文档对应章节可覆盖）。
  - 新增 `scripts/doc_zone_manager.py`：以固定标题锚点（`## 📝 使用案例 & 踩坑记录` / `## 📋 更新日志`）切分 Overwrite / Preserve / Append 三区；`sync_doc_zones()` 为唯一编排入口，`update_overwrite_zone()` 对每个待删 block 强制 `ZoneMap.zone_of()` 归属断言（越界即 `raise`），Preserve Zone 一律不 update / 不 delete，Changelog 只追加。
  - L3 断言 `assert_zone_integrity()`：两个锚点各出现**恰好 1 次** + 写前采样的 Preserve Zone 正文在 RAW 回读中**仍然存在**；任一不满足即 `raise GuardrailViolation`，禁止静默 WARNING。
  - 老文档兼容：无锚点 / 锚点重复 / 顺序颠倒一律**安全降级** —— 整篇视为不可动 Preserve Zone，仅末尾补建缺失锚点章节，打印 `[ZONE-DEGRADED]` 并落 `.forge_receipt.json` 的 `doc_zone_degraded`，绝不误删既有正文。
  - 新建文档路径：`register_skill.py --emit-new-doc-markdown` 产出「Overwrite → Preserve（占位 `[待补充使用案例]`）→ Append」三分区骨架，让文档出生即合规。
  - `register_skill.py`：接入 `sync_doc_zones()`（版本标识同步之后、Wiki Mount 之前），新增 `--skip-doc-zones` 调试开关，metadata 落 `doc_zone_synced` / `doc_zone_sync` / `doc_zone_degraded`。
  - 健壮性踩坑：Preserve 锚点标题自带 `&`，附件 `href` 也常带未转义 `&`，严格 XML 解析必崩 → 新增 `sanitize_doc_xml()` 把非法实体的裸 `&` 补成 `&amp;`；`SKILL.md` 的文档模板骨架里本就写着 `## 🔑 触发词`，故 `extract_skill_md_section()` 必须先 `_strip_fenced_blocks()` 剔除围栏，否则会把模板占位符灌进飞书文档。
  - 断言样本取「补建锚点前 ∪ 补建后」的并集：补建只 append 不删除，故补建前采到的人工正文必须依然存在；若用重扫结果覆盖原样本（往往只剩占位提示），存在性断言会退化成自证，等于放弃保护既有沉淀。
  - 新增 `scripts/test_doc_zones.py` 离线自检（25 例全绿）：覆盖边界切分、老文档降级、锚点重复 / 顺序颠倒、标题空格与 `&` 变体、非法 XML 熔断、围栏剔除。

- **V5.22**: 收紧 `is_own_skill_zip()` 的版本后缀匹配，杜绝跨技能 ZIP 块误删。此前 `<父名>-v4.zip` 会被宽松正则判为父技能自身旧块，若未来出现「同名前缀的独立技能」与父技能共享同一说明文档，父技能 forge 会静默删除该独立技能的 ZIP 块。现要求剥离技能名前缀后的剩余后缀必须为空 / 带点号的纯数字版本（`_5.21`、`_v5.22`）/ `(1)` 去重后缀 / `_latest` 白名单；任何含字母语义的后缀（`-v4`、`_v4`、`-beta`、`_old`）一律判为「异物块，只报告不删除」。新增 `scripts/test_is_own_skill_zip.py` 自检（9 例全绿）。

- **V5.21**: 把 ZIP 回挂 upsert 的软降级全部升级为物理熔断，补齐 V5.19 遗留的最后一道缺口。
  - **根因**：V5.19 已实现 `prune_stale_zip_blocks()`（扫描 → 删旧 → 插新 → 置顶 → 回读），但四条失败路径（枚举失败 / 删除失败 / 回读失败 / 唯一性数量 != 1）全部只打印 `⚠️ WARNING` 后 `return report`，流水线继续宣称发布成功。这是典型的「应然 ≠ 实然」假成功：护栏写了，但没长牙。
  - **修复**：四条路径统一改为 `raise GuardrailViolation`。因 `prune_stale_zip_blocks()` 在新块已插入并断言之后才执行，熔断绝不会导致文档失去安装包，故熔断是安全的。异物块（其他技能的 ZIP）保持「只报告不删除」——删除他人资产属破坏性操作，需人工判断。
  - **Verification 第 4 条**改写为 UPSERT 唯一性口径（出现次数必须 == 1），并在 Red Flags 新增「只 append 不清旧块」「唯一性失败降级 WARNING」两条反合理化条款。
  - **配套治标**：同批清理 8 篇存量说明文档共 22 个幽灵 ZIP 块（info-miner 14→1、team-travel 3→1、multi-source-sync 3→1、us-am-stats-sync ×2 各 2→1、centralized-transmitter 2→1、media-fetcher 2→1、zero-trust-qa-checker 2→1），判定基准为 `drive metas create_time` 最新 + 本地 zip size 交叉断言，全部 RAW 回读通过。

- **V5.20.2**: 修复 forge 回执落点错位（Path.cwd() 硬编码）。
  - `register_skill.py` 的 `metadata_path = Path.cwd() / "metadata.json"` 把回执写到流水线执行目录而非目标技能目录，产生散落且内容错位的幽灵 `metadata.json`（曾被误当成 Skill ID 权威来源）。现统一改为 `skill_dir / ".forge_receipt.json"`（无 `--skill-dir` 时才回落 `Path.cwd()`），Cloud Publish 阶段的二次落盘与日志文案同步改名，杜绝「一处改名、日志仍喊 metadata.json」的不一致。
  - 仓库根 `.gitignore` 全局黑名单区追加 `**/.forge_receipt.json`：回执是每次 forge 可再生产物，永不入 Git（与 `*.zip` 只上飞书云盘同口径）。
  - 清理目录内 5 个错位幽灵 `metadata*.json`；重申 **Skill ID 唯一事实来源为飞书台账【专属技能清单】**。
  - 版本 patch 位保留方案（V5.20 引入的 `_parse_version` / `_format_version` / `normalize_version_text` / `bump_version patch` 档）本轮回归验证通过，并已移植到 `skill-forge-pipeline-v4`。
- **V5.20**: 堵死「说明文档正文版本未同步」的连续两轮假成功缺陷，并修复版本号 patch 位截断。
  - **Task 1（L3 断言）**：`register_skill.py` 重写 `sync_version_to_skill_doc_via_mcp()`，新增 `collect_doc_version_lines()` / `_rewrite_doc_version_line()` / `assert_doc_body_version_synced()`。标题内嵌版本 + 带标签版本全量改写，写后 2s RAW 回读断言，Wiki Mount 后再断言一次；找不到版本标识或仍为旧版即 `raise GuardrailViolation("【文档版本未同步】...")`，删除原 `skip SSOT doc sync` 静默分支。结果落 `metadata.json` 的 `doc_version_synced` / `doc_version_sync`。
  - **Task 1 根因（三重叠加）**：旧正则只认 `version:` 标签认不出标题 `V5.19`；替换串误写 `r"\\1"` 导致即便命中也写成字面量；`.lark.md` 兜底下载无 `<!-- BLOCK_n -->` 标记使按块遍历永不进入替换分支。
  - **Task 2（Code Review 修复）**：① `_normalize_version_to_int_pair` / `_format_version_pair` 升级为 `_parse_version` / `_format_version` / `normalize_version_text`，**保留 patch 位**（`v1.6.1` 不再被截成 `1.6`）；② `bump_version` 新增 `patch` 档，三段版本 minor/major 升迁自动补 `.0`；③ `--bump` 新增 `patch` 选项与交互式第 3 项；④ `create_skill_zip` 新增运行时产物黑名单（`.tmp` / `.runtime` / `downloads` / `snapshots` / `output(s)` / `*.zip` / `*.mp4` / `*.part`）与 >50MB 体积告警，防重演 245MB 技能包被 pre-push 拦截。
  - CDA L1：Common Rationalizations 新增 3 条、Red Flags 新增 3 条；Verification 新增第 14 条「说明文档正文版本回读断言验收」；Defaults 新增版本形态与回读断言默认值。

- **V5.19**: 新增第四步「Cloud Publish 云端发布」，并将本技能改名 `skill-forge-pipeline-v4` → `skill-forge-pipeline`（Skill ID `SKILL-FORGE-PIPELINE` 不变）。
  - 根因：此前流水线止步于 Git Push，技能虽进了 GitHub 仓库，却仍是 Aime 本地草稿，必须人工去界面点「上传到云端」才真正生效 —— 这是自动化链路上最后一段手工缺口，也是「已发布」错觉的来源。
  - 新增 `scripts/cloud_publish.py`：唯一上传命令 `aime skill upload <绝对路径>`；upload 前先 `aime skill draft list`，缺失则 `aime skill draft create`；upload 后强制 `aime -o json skill list` + `draft list` 云端回读断言（云端 ID 非空 + `cloudVersionTime > 0` 或已出草稿 + `UpdatedAt` 相对基线推进）。
  - L3 断言层：`validate_cloud_publish_args()` / `assert_cloud_skill_present()`，失败即 `raise`；失败路径写 `.ephemeral_pool/cloud_publish_failures.jsonl`、在 `SKILL.md` 标记 `⚠️ 需手动上传`、metadata 落 `cloud_publish_status=failed`，并输出手动补救命令。
  - **断言口径校准（真机验证）**：不得用 `isDraft == False` 判定上传成功 —— 只要本地仍存在同名草稿目录，`skill list` 中云端记录依旧是 `isDraft=True`，用它断言会误熔断。
  - `register_skill.py`：新增 `--cloud-scope user|space`、`--enable-by-default` 参数与 `run_cloud_publish()`，在 Git Push 断言 PASS 后自动调用；Cloud Publish 结果写入 `metadata.json`（`cloud_publish_status` / `cloud_scope` / `cloud_published_at` / `cloud_skill_id` / `cloud_publish_dlq` / `cloud_publish_error`）。顺带修掉一处 `.lark.md` 兜底路径的旧名硬编码，改为 `Path(__file__)` 推导。
  - 合规默认值：`--cloud-scope` 默认 `user`（禁止默认 `space`），`--enable-by-default` 默认 `false` 且仅 `space` 有效；权限墙下**严禁**自动切换 scope 或换空间重试，必须提示用户联系项目空间管理员加成员并标记需手动上传；调试开关 `SKIP_CLOUD_PUBLISH=1`。
  - 改名：目录经 `git mv` 迁移（保留 Git 历史），`SKILL.md` frontmatter / 标题 / 操作示例 / 自举约束、`celebrate_skill.py`、`dual_track_atomic_write.py` 等旧名引用全量替换；`CHANGELOG.md` 历史条目保留旧名以保真。
  - CDA L1：Common Rationalizations / Red Flags 新增云端发布与改名相关条款；Verification 新增第 13 条「云端发布验收」。

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

Skill 资源位于 `user_skills/skill-forge-pipeline`，**文档中所有相对路径/命令均相对于此目录**：

- 读取/编辑：使用 `view_skill` 或编辑器操作本目录。
- 执行流水线辅助脚本：

```bash
cd user_skills/skill-forge-pipeline \
  && python3 scripts/register_skill.py \
    --name "skill-forge-pipeline" \
    --desc "自动化技能创建、升级、打包发布、归档与云端上线流水线（含 CDA 自检与云端发布断言）" \
    --path "https://bytedance.larkoffice.com/docx/HgY3dJBPfowjJfxWnxWcvItJncg" \
    --wiki-node-token "GU0ewkyaGi4i5nkwBtNcM3aPn9g" \
    --bump minor \
    --skill-dir "user_skills/skill-forge-pipeline" \
    --id "SKILL-FORGE-PIPELINE"
```

## ☁️ 云端发布记录

- `cloud_publish_status`: **SUCCESS**
- `skill_name`: `skill-forge-pipeline`
- `version`: `5.27`
- `cloud_scope`: `user`
- `cloud_published_at`: `2026-08-22 01:39`
- `cloud_skill_id`: `899c40be-6e8b-4386-9040-8438a1095efc`
