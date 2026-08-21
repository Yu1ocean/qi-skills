# Changelog - skill-forge-pipeline

> 说明：v5.19 起技能更名为 `skill-forge-pipeline`（Skill ID `SKILL-FORGE-PIPELINE` 不变）。以下历史条目中的旧名 `skill-forge-pipeline-v4` 保留原样以保持记录保真。

## v5.21 (2026-08-21)

- **修复 ZIP 回挂 upsert 的四条静默降级路径（软护栏 → 物理熔断）**。
  - v5.19 引入的 `prune_stale_zip_blocks()` 已具备完整 upsert 编排，但「枚举失败 / 删除失败 / 回读失败 / 唯一性数量 != 1」四条路径均只打印 `⚠️ WARNING` 后返回，流水线照常判定发布成功——护栏形同虚设，幽灵安装包继续堆积且无人察觉。
  - `register_skill.py`：四条路径统一改为 `raise GuardrailViolation`，并在 docstring / 内联注释写明「本函数在新块插入并断言之后执行，故熔断不会导致文档失去安装包」的安全性论证。异物块维持「只报告不自动删除」。
  - `SKILL.md`：Verification 第 4 条改写为「ZIP 文件块出现次数必须 == 1」的 UPSERT 断言口径，废弃「存在即通过」；Red Flags 新增「只 append 不清旧块」与「唯一性失败降级 WARNING」两条。
- **同批治标**：清理 8 篇存量说明文档共 22 个幽灵 ZIP 块，判定基准 = `lark-cli drive metas batch_query` 的 `create_time` 最新 + 本地 `user_skills/<skill>.zip` size 交叉断言（不按体积大小判新旧）。清理后每篇文档 RAW 回读均为「恰好 1 个 ZIP 块」。附带清掉 info-miner 的 `info-miner_latest.zip` 异名变体。

## v5.20 (2026-08-21)

### Task 1 — 补 L3 断言：说明文档正文版本回读
- **缺陷**：每次锻造后，飞书说明文档的标题/正文版本号仍停留在旧版，连续两轮「假成功」。
- **根因（三重叠加）**：
  1. 版本正则只认「带标签」形态（`version:` / `版本号：`），认不出标题里的 `(Forge Pipeline V5.19)`；
  2. 替换串误写成 `r"\\1"`（字面反斜杠 + 1，而非分组反向引用），即便命中也会写坏；
  3. `.lark.md` 兜底下载不含 `<!-- BLOCK_n | id -->` 标记，导致「按块遍历」的 while 循环永远进不了替换分支，最终只打印一句 `⚠️ No explicit version marker found in doc; skip SSOT doc sync.` 静默放行。
- **修复**：重写 `sync_version_to_skill_doc_via_mcp()`，新增
  - `collect_doc_version_lines()`：识别标题内嵌版本 + 带标签版本（含 `` `version`: `5.19` `` 反引号变体），刻意**不匹配** Changelog 历史行以保真；
  - `_rewrite_doc_version_line()`：逐行 `str_replace` 全量改写；
  - `assert_doc_body_version_synced()`：写后 `sleep 2s` 重新下载文档做 RAW 回读，断言所有版本标识 == 本次锻造版本；不通过 `raise GuardrailViolation("【文档版本未同步】...")`，全文无版本标识同样 `raise`（禁止静默跳过）。
- **双次断言**：写入后 + Wiki Mount 之后各断言一次（防搬家把旧版本带回），结果落 `metadata.json` 的 `doc_version_synced` / `doc_version_sync`。

### Task 2 — Code Review 修复
- **版本号 patch 位截断（已知 BUG）**：`_normalize_version_to_int_pair()` / `_format_version_pair()` 只取 `(major, minor)`，`v1.6.1` 被静默降级为 `1.6`。改为 `_parse_version()` → `(major, minor, patch|None)` + `_format_version()` + `normalize_version_text()`，**两段进两段出、三段进三段出**。
- **`bump_version` 语义补全**：新增 `patch` 档；三段版本做 minor/major 升迁时自动补 `.0`（`1.6.1` --minor--> `1.7.0`）；`--bump` 新增 `patch` 选项与交互式第 3 项，非交互报错文案同步更新。
- **技能包体积护栏**：`create_skill_zip()` 新增运行时产物黑名单（`.tmp` / `.runtime` / `downloads` / `snapshots` / `output(s)` 目录，`*.zip` / `*.mp4` / `*.part` / `*.pyc` 后缀）与 >50MB 醒目告警，防重演 245MB 技能包被 pre-push 熔断。
- **文档**：`SKILL.md` Common Rationalizations +3 / Red Flags +3 / Verification 第 14 条 / Defaults 新增版本形态与回读断言默认值。

### 遗留观察项（未改，风险可控）
- `call_with_retry()` 会对 `GuardrailViolation` 同样重试 3 次：对最终一致性场景（文档回读）有益，但对纯参数类违规属无谓重试，建议后续按异常类型分流。
- `metadata.json` 写入 `Path.cwd()`，路径依赖调用现场；按 AGENT.md R4，它是单次发布回执，不应纳入 Git 跟踪。
- 多处 `except Exception` 宽捕获（枚举/快照类降级路径），已有醒目 WARNING，但建议收窄异常类型以免掩盖真实缺陷。

## v5.19 (2026-08-21)
- **新增第四步「Cloud Publish 云端发布」**：此前流水线止步于 Git Push，技能虽已进 GitHub `Yu1ocean/qi-skills`，却仍是 Aime 本地草稿，必须人工去界面点「上传到云端」才真正生效 —— 这是自动化链路上最后一段手工缺口。
- 新增 `scripts/cloud_publish.py`：
  - 唯一上传命令 `aime skill upload <技能绝对路径>`；upload 前先 `aime -o json skill draft list`，缺失则 `aime skill draft create <绝对路径>`。
  - upload 后强制云端回读断言 `assert_cloud_skill_present()`：`aime -o json skill list` 存在同名技能且 `ID` 非空 + `draft list` 的 `cloudVersionTime > 0`（或已不在草稿列表）+ 云端 `UpdatedAt` 相对 upload 前基线有推进。**禁止只看 upload 退出码**。
  - **断言口径校准（真机验证）**：初版用 `isDraft == False` 判定成功不成立 —— 只要本地存在同名草稿目录，`skill list` 中云端记录仍为 `isDraft=True`，会误熔断。
  - L3 前置校验 `validate_cloud_publish_args()`：技能目录存在 + 含 `SKILL.md` + `--cloud-scope ∈ {user,space}`；`--enable-by-default` 仅 `space` 有效。
  - 失败路径（禁止静默）：输出醒目 `ERROR` + `SKILL.md` 标记 `⚠️ 需手动上传` + 写死信队列 `.ephemeral_pool/cloud_publish_failures.jsonl` + 输出手动补救命令。
  - 权限墙下**严禁**自动切换 scope / 换空间重试，必须提示用户联系项目空间管理员加成员。
  - CLI：`--skill-dir` / `--version` / `--cloud-scope` / `--enable-by-default` / `--aime-bin` / `--dry-run` / `--strict`；调试开关 `SKIP_CLOUD_PUBLISH=1`。
- `scripts/register_skill.py`：新增 `--cloud-scope user|space`、`--enable-by-default` 与 `run_cloud_publish()`，在 Git Push 远端 SHA 断言 PASS 后自动调用；结果写入 `metadata.json`（`cloud_publish_status` / `cloud_scope` / `cloud_published_at` / `cloud_skill_id` / `cloud_publish_dlq` / `cloud_publish_error`）。顺带修掉 `.lark.md` 兜底路径的旧名硬编码（改为 `Path(__file__)` 推导）。
- **技能更名**：`skill-forge-pipeline-v4` → `skill-forge-pipeline`，目录经 `git mv` 迁移保留 Git 历史；`SKILL.md` frontmatter/标题/操作示例/自举约束、`celebrate_skill.py`、`dual_track_atomic_write.py`、`AGENT_GIT_HOOK.md`、`skill-heatmap-generator` 名录、`zero-trust-qa-checker` / `speech-knowledge-precipitation` 的 SSOT marker 注释同步替换。
- `SKILL.md` 升级至 V5.19：新增「### 5. Cloud Publish 云端发布」章节、Verification 第 13 条「云端发布验收」、Defaults 云端 8 项默认值，Common Rationalizations / Red Flags 各新增云端发布与改名相关条款。

## v5.16 (2026-08-21)
- **修复 Archive 阶段 ZIP 文件块「无限 append」缺陷**：`attach_zip_to_doc_via_mcp` 每次只调 `lark-cli docs +media-insert` 追加新块、从不清理同名旧块，导致说明文档累积多个历史版本 `skill-forge-pipeline-v4*.zip` 文件块（并混入 1 个无关技能 ZIP）。
- `scripts/register_skill.py` 新增：
  - `list_doc_zip_file_blocks(doc_url)`：走 `lark-cli docs +fetch --doc-format xml --detail with-ids` 解析 `<figure><source name/token>` 枚举 ZIP 文件块，替代已失效的 `docx.v1.document_block.list` 内部代理（该代理现返回 `unsupported lark method_name`）。
  - `is_own_skill_zip(file_name, skill_name)`：同名旧块识别，兼容 `_v1.2` / `-1.2` / ` (1)` 等版本后缀变体，拒绝误判 `skill-x-extra.zip` / 其他技能。
  - `delete_doc_blocks(doc_url, block_ids)`：`docs +update --command block_delete --block-id <逗号分隔>` 批量物理删除。
  - `prune_stale_zip_blocks(doc_url, skill_name, new_block_id)`：编排「删同名旧块 → sleep 2s → 回读断言本技能 ZIP 块数量 == 1 且 block_id == 新块」，异物块只报告不删除，枚举/删除失败降级为「只插入不删除」+ 醒目 WARNING（不熔断流水线）。
- 执行顺序锁定：插新块 → `move_block_to_doc_begin` 归位 → `assert_zip_block_at_doc_begin` 断言 → 再删旧块，避免「删完插失败导致文档裸奔」。
- 修掉 `list_doc_file_blocks()` 在代理返回非 0 code 时静默返回 `[]` 的隐患（改为 `raise`），防止清理动作静默变 no-op。
- **`SKILL.md` 升级至 V5.16**：Archive 章节新增「Archive 步骤文件块替换规则」6 条子款；Red Flags 新增 3 条；Verification 新增第 11 条「文件块唯一性断言」。

## v5.15 (2026-08-21)
- **关联决策**：DEC-20260821-001「决策录入必须双轨原子写入，单轨成功即判失败」（起因：forge 子特工只写飞书镜像台账、从未 append 本地 SSOT `memory/topics/decision-registry.md`，形成孤儿行，漂移数天不可见）。
- **新增 L3 断言层熔断脚本** `scripts/dual_track_atomic_write.py`：
  - 事务块语义：飞书镜像 MCP 写入成功后**立刻**执行本地 SSOT append，两步绑定为一个事务，中间不允许插入其他动作或等待用户确认。
  - RAW read-after-write 双轨断言：轨道 A 回读本地末条 `- id: DEC-...`、轨道 B 通过 `lark-cli` 回读飞书镜像末行 ID，均需 == 目标 ID；任一轨失败即 `raise` 熔断，严禁静默成功。
  - 失败即孤儿标记：写入死信队列 `.ephemeral_pool/orphan_decisions.jsonl`（`decision_id` / `failed_track`(local|mirror) / `error` / `timestamp` / `suggested_fix` / `⚠️[孤儿待修复]`）。
  - CLI：`--dry-run`（零副作用前置校验）、`--verify-only <DEC-ID>`（事后巡检）、`--inject-failure local|mirror`（故障注入自测）。
  - 复用 `tools/sync_decision_registry.py` 的鉴权与飞书读写链路（`resolve_sheet_url` / `get_sheet_meta` / `read_range` / `write_range` / `raw_verify`），不重造轮子。
- **`SKILL.md` 升级至 V5.15**：新增独立章节「双轨原子写入约束 (Dual-Track Atomic Write)」（适用范围 / 事务块绑定顺序 / 双轨断言规则 / 孤儿标记流程 / 调用示例）；Common Rationalizations 新增 2 条、Red Flags 新增 3 条、Verification 新增第 10 条「双轨原子写入验收」、Defaults 新增镜像台账 / SSOT / DLQ / 2s 回读默认值。
- 真机验证：① `--dry-run` 前置校验 PASS（exit 0，无副作用）；② `--verify-only DEC-20260821-001` 双轨断言 PASS（local last_id 与 mirror row29 均为 DEC-20260821-001）；③ 故障注入 `--inject-failure mirror` / `local` 均正确 `raise` 熔断（exit 1）并落 DLQ 两条 `⚠️[孤儿待修复]` 记录。

## v5.14 (2026-08-17)
- **修复 P1 级假成功缺陷（幽灵资产）**：`user_skills/scripts/post_forge_git_push.sh` 原先执行 `git push origin main`，当工作副本 HEAD 处于特性分支（如 `aime/us-am-stats-sync-v16`）时推送的是本地陈旧的 `main` ref，退出码仍为 0，导致流水线宣称「已 push 到 qi-skills」而新版本 SKILL.md / 脚本根本没到 GitHub（今日 v1.9 / v2.0 / v2.1 / v2.2 四次发布全部靠人工 `git push origin HEAD:main` 补推）。
- push 命令改为 `git push origin HEAD:main`，把当前 HEAD 显式推到远端 `main`。
- **新增远端回读断言**：push 后回读 `git ls-remote origin refs/heads/main`，与 `git rev-parse HEAD` 比对 SHA；不一致即判定 push 未生效，以非 0 退出码退出并输出醒目错误。禁止仅凭 `git push` 退出码判定成功。
- 新增 non-fast-forward 自愈链路：`git fetch origin main` → `git rebase origin/main`（冲突则回滚改 `git merge`）→ 重试 push 一次；仍失败则非 0 退出并报告「需人工介入」。
- 新增结构化审计日志：`local_branch` / `local_head` / `remote_main` / `assert_result`(PASS|FAIL)。
- 无 staged 变更时不再提前 `exit 0`，仍继续 push + 断言，避免历史 commit 漏同步。
- 新增 `POST_FORGE_DRY_RUN=1` 故障注入开关（跳过真实 push、保留断言）；`SKIP_POST_FORGE_GIT_PUSH=1` 调试语义保持不变。
- `SKILL.md` 同步升级至 V5.14：Red Flags 新增「仅凭 git push 退出码判定成功 / 未做远端 SHA 比对」，Verification 新增第 8 条远端 SHA 断言，Post-Forge Git Push Hook 与 Git 自动归档章节写明 `HEAD:main` 语义。
- 真机验证：①「HEAD 在特性分支 + 本地 main 落后」场景 → HEAD 正确推到远端 main，assert PASS；②`POST_FORGE_DRY_RUN=1` 故障注入 → assert FAIL 且退出码 1；③ non-fast-forward 场景 → rebase 后重试成功，assert PASS。
- **附带修复（同版本）**：ZIP 文件块回挂位置漂移。`register_skill.py` 的 `attach_zip_to_doc_via_mcp` 原先只调用 `lark-cli docs +media-insert`，而该命令默认**追加到文档末尾**，使 ZIP 挂在文档尾部而非「标题正下方」，属于同一类「命令成功但契约未达成」的假成功。新增 `_parse_block_id_from_attach_output()` / `move_block_to_doc_begin()`（`block_move_after`，anchor = 文档 root token）/ `assert_zip_block_at_doc_begin()`（回读文档 XML 断言首个正文块 id），不符即 `raise` 熔断。
- 台账去重：将历史遗留的重复行（`SKL-2604-013`，v5.5）提升为唯一权威行并写入 `SKILL-FORGE-PIPELINE` / 5.14，清空本次新增的重复行，RAW 回读核对通过。

## v5.13 (2026-07-30)
- 正式将 Git 自动归档写入 `SKILL.md` 的 Archive 后置 SOP：明确调用 `user_skills/scripts/post_forge_git_push.sh <skill_name> <version>`、目标仓库 `https://github.com/Yu1ocean/qi-skills`、commit message 格式与失败汇报口径。
- 在约束条件中固化每次 forge/upsert 完成后必须触发 Git push hook，并明确 `skill-forge-pipeline-v4` 自举迭代同样需要触发 Git push。

## v5.11 (2026-06-13)
- 修复 `register_skill.py` 在“grant drive full_access”阶段误把 `AIME_USER_CLOUD_JWT` 当作飞书 Access Token 直调 Drive Permission API，导致 `code=99991668 / Invalid access token` 的断链。
- ZIP 文件块回挂后，改为调用 `user_skills/feishu-doc-writing-guide/scripts/grant_doc_permissions.py` 兼容包装器，底层走 `ensure_doc_in_personal.py -> mcp_lark_move_lark_doc.py` 的 MCP personal-space 修复链路，恢复 ZIP 资产可管理访问权后再继续 metadata / 台账闭环。

## v5.10 (2026-06-13)
- 修复 `register_skill.py` 的 ZIP 附件 `file_token` 回捞断点：当 `mcp_lark_update_lark_doc` 的返回值不再直接暴露 `file_token`，且 `list_doc_file_blocks` 路径拿不到新块 token 时，新增第三层兜底——下载最新 `.lark.md` 并从文档内容里解析 `/file/<token>` / `file_token` 线索，避免在权限闭环前误熔断。
- 同步增强 `parse_file_token_from_attach_output()` 的兼容口径，支持更宽松的 token / URL 形态解析，降低 MCP 输出格式轻微漂移导致的断链概率。

## v5.9 (2026-06-08)
- `register_skill.py` 在同步【专属技能清单】时，新增 `updated_at` 文本时间拦截器：会先把 `YYYY-MM-DD` / `YYYY-MM-DD HH:MM` 转成飞书日期序列值，再交给 `omni-asset-archiver` 入库，避免技能台账的日期列被写成纯文本。
- 该修复优先用于 `TEAM-TRAVEL-DASHBOARD-GENERATOR` 的技能迭代链路，确保 SG 主台账中的日期列继续保持飞书原生日期类型。

## v5.8 (2026-06-02)
- `register_skill.py` 的技能台账同步链路由“下载 xlsx → 只改版本号 → 回传”切换为调用 `omni-asset-archiver/scripts/archiver_driver.py` 做整行 upsert。
- 新注册技能若未命中旧行，将自动向【专属技能清单】增行；已存在技能则继续按 `Skill ID` 幂等更新，避免只会改版本、不会补录的断链。
- `--skip-ssot-sheet-sync` 语义同步升级为“跳过技能台账整行 upsert”，与新的 Archive 行为对齐。

## v5.7 (2026-05-24)
- 新增 Wiki Mount Phase：`register_skill.py` 现在会在 ZIP 文件块回挂完成后、`metadata.json` 落盘前，强制调用飞书 Wiki MCP 挂载链路，将说明文档迁入「Aime 技能库」Wiki 节点。
- 新增 `--wiki-node-token` 参数，默认指向 Aime 技能库根节点 `GU0ewkyaGi4i5nkwBtNcM3aPn9g`；支持按需覆盖到指定 Wiki 节点。
- `metadata.json` 结构新增 `wiki_url`、`wiki_node_token` 字段，作为发布与归档的断言信息。
- 若 Wiki 挂载失败，发布流程会在 metadata 落盘前直接熔断，不再允许假装发布成功。

## v5.6 (2026-05-22)
- 将“首次发布”判定逻辑从写死的 `0.0 / 0.1 / 0.2` 升级为统一识别所有 `0.x`。
- `register_skill.py` 现在只要发现目标技能的 Major 版本号为 `0`，就会忽略 `--bump`，直接设为 `1.1`（或 `--initial-version` 指定值），不再执行 `+0.1` 的占位小迭代。

## v5.5 (2026-05-20)
- 新增「首次发布起始版本号」机制（用户奇楠 2026-05-20 指示）：
  - 新增 `--initial-version` CLI 参数，默认 `1.1`。
  - 新增内部辅助函数 `is_initial_version()`，识别 `0.0` / `0.1` / `0.2` 这类脚手架占位值。
  - 当 `register_skill.py` 在 Archive 阶段检测到 SKILL.md 仍为脚手架占位值时，**忽略 `--bump`**，直接将版本设为 `1.1` 并回写 SKILL.md。
  - 已 ≥ `1.0` 的存量技能不受影响，继续按 `--bump major|minor` 升迁。

## v5.3 (2026-05-03)
- Archive 阶段新增「版本同步总线（SSOT）」机制：
  - 以目标技能 `SKILL.md` 的 `version:` 为单一事实来源。
  - 归档时支持 Major(+1.0) / Minor(+0.1) 两种升迁，并回写覆盖本地 `SKILL.md`。
  - 强制通过 `bytedcli-auth` + MCP `lark_sheets_update` 定向覆写【专属技能清单】的【版本号】列，并执行写后读回校验。
  - （若存在版本标识）通过 MCP 对飞书说明文档进行版本号替换。

## v5.2.0 (2026-04-27)
- 新增 Forge 阶段强制 Checkpoint：`CDA-Guardrails-Selfcheck`。
  - 自动风险分级（高/中/低）。
  - 按风险等级强制校验 L1/L2/L3 三层覆盖，失败即熔断。
  - 反例库 / 模板 / 评估表下沉至 `resources/cda_guardrails/`，供 Forge 时一键复制。

## v5.1.0
- 飞书说明文档模板升级，新增「🔑 触发词」与「📖 案例实录 (Best Practice)」。
