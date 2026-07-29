# Changelog - skill-forge-pipeline-v4

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
