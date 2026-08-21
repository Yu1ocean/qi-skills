# Changelog - skill-forge-pipeline-v4

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
