---
name: live-material-fraud-auditor
version: 2.1
description: 对 TikTok / Pearl 等平台的直播回放做 prompt-driven 语义违规审核，注册 TikTok Shop 达人及内容规则白皮书的 27 类违规、当前默认启用 25 类（拍卖与静态画面两类按用户指令暂不纳入审核范围；注册类型含材质造假、品牌授权、假货仿冒、货不对板、虚假定价、误导折扣、夸大绝对化、医疗功效、体重管理、性健康、禁限售、赌博、赠品促销、拍卖、站外引流、刷单冒充、恶意比较、慈善、IP 侵权、非原创、AIGC、未成年人、性暗示、耸人听闻、不相关推广、前后对比、静态画面）。适用于需要产出完整逐字稿、可取证命中表与飞书审核报告的直播合规质检；覆盖视频摄入探针、60 秒分段 ASR、语义窗口判定、反幻觉证据逐字回溯、风险分级、人工复核隔离与断点续跑。
author: yuqinan
---

# 直播违规语义审核员 (live-material-fraud-auditor)

对直播回放做**全类型违规语义审核**，产出可取证的逐字稿 + 命中表 + 飞书审核报告。

审核对象是「主播说了什么」，而不是「商品页写了什么」，所以整条链路的可信度完全建立在**音频被完整摄入、时间戳绝对准确、命中可逐字回溯**这三件事上。下面所有护栏都是为了让这三件事不被"看起来完成了"糊过去。

v2.0 用**语义判定**取代了 v1.x 的关键词库匹配。关键词库的根本缺陷是「换个说法就漏」——主播把 `replica` 说成「和专柜一模一样」就绕过了；而且每加一类违规都要人工整理一套词表。语义判定只需要一段自然语言 `judge_prompt`，扩展新违规类型 = 在 `audit_config.yaml` 里加一个 block。

## 🔑 触发词

- 核心关键词：
  - 直播合规审核 / 直播违规语义审核
  - 直播材质审核 / 材质造假审核
  - 假货审核 / 仿冒品审核
  - 品牌授权宣称 / 正品宣称
  - TikTok Shop 违规审核 / 达人内容合规
  - live-material-fraud-auditor
- 典型指令示例：
  > 帮我审核这场直播回放，按 TikTok Shop 规则白皮书全类型过一遍
  > 这个 Pearl 回放 roomId=xxx，重点看有没有假货、材质造假和品牌授权问题
  > 只跑材质造假 + 假货 + 站外引流三类，出飞书审核报告

## Common Rationalizations（常见借口库）

以下话术一旦出现，等价于准备伪造审核结论，必须立刻停下并回到 SOP：

- "回放 20 小时太长，抽查几段有代表性的就够了。"
- "最后几分钟抽出来是空 WAV，跳过不写说明也没人看得出来。"
- "一段切 5 分钟效率更高，ASR 应该扛得住。"
- "先用片段内的相对时间戳，最后再统一加偏移。"
- "写完飞书就算落盘了，回读校验太慢先跳过。"
- "`official` 命中就是品牌宣称，直接算高风险，不用回听。"
- "覆盖到 80% 已经能得出结论了，汇报时先说全量完成。"
- "`feishu-doc-writing-guide` 太重，我直接调 lark API 写文档更快。"
- **"429 限流重试太慢，跳过这几个窗口不影响结论。"**（→ 跳掉的正好可能是唯一一条高风险）
- **"模型给的证据大意对得上，不用逐字核对逐字稿。"**（→「大意对得上」正是幻觉的典型形态）
- **"静态画面类型也一起开着吧，多审一类总没坏处。"**（→ 纯视觉类在 ASR-only 链路上只会造幻觉）
- **"语义模式上了，关键词扫描就删掉吧。"**（→ legacy 通道是语义漏检的兜底，不删）
- **"27 类全开太慢，先跑材质和品牌就说全类型审完了。"**（→ 实际启用类型必须写进报告）

## Red Flags（危险信号）

出现任意一条，必须熔断或要求人工确认，不得继续推进结论：

- 写入飞书后**没有 RAW 回读**，就宣称"已更新 / 已完成"。
- 汇报的覆盖范围**大于**实际 RAW 校验通过的区间（虚报全量完成）。
- 把 ASR 疑似项（如 `official` 疑似"老主顾"误识别）当作**已确认事实**写进审核结论。
- 尾段抽出空 WAV 但**未在覆盖说明中显式写出**，让读者误以为全程有效音频。
- 单段音频**超过 60 秒**仍送 ASR（超时与时间戳漂移风险）。
- 逐字稿使用**片段内相对时间戳**，而不是回放绝对偏移。
- 绕过 `user_skills/feishu-doc-writing-guide`，裸调飞书 OpenAPI / lark MCP 直写文档。
- 断点文件缺失或未更新，续跑时重跑已完成区间 / 漏跑未完成区间。
- 命中表缺少「时间戳 + 原文」任一项，导致命中无法回溯取证。
- **存在 `unjudged_windows` 却宣称全量判定完成。**
- **输出命中的 `evidence_text` 无法在逐字稿中逐字定位。**
- **报告中出现 `enabled: false` 的违规类型命中。**
- **把 `modality: visual` 或 `audio+visual` 类型的命中当作已确认结论（未看画面）。**
- **直接改脚本硬编码违规判定规则，而不是改 `audit_config.yaml`。**

## Verification（强制验收清单）

宣称"审核完成"时，必须同时满足：

1. **摄入可证**：已用 `yt-dlp-media-downloader` 完成 probe（或 m3u8 降级 probe），并留有 probe 输出。
2. **切片合规**：全部音频片段时长 ≤ 60 秒，且每段起止均为回放绝对偏移；`validate_segment_duration()` 全部通过。
3. **时间戳绝对**：逐字稿所有时间戳为 `HH:MM:SS` 绝对偏移；`validate_timestamp_absolute()` 通过。
4. **命中可回溯**：命中表每条含「违规类型 + 时间戳 + 原文证据 + 风险等级 + 需人工复核 + 判定理由」六要素，由 `semantic_violation_judge.py` 产出而非手写；`validate_semantic_hit_row()` 通过。
5. **疑似项隔离**：所有 `need_human_review=true` 的命中单独列入「待人工复核清单」，未混入已确认结论。
6. **写后回读**：每批写入飞书后经 `assert_raw_readback()` 校验通过；未通过即熔断。
7. **覆盖如实**：覆盖说明包含实际覆盖区间、总时长、尾段空 WAV 情况；`validate_coverage_report()` 通过。
8. **断点一致**：断点文件记录的最新 `revision_id` 与已覆盖区间，与飞书文档实际内容一致。
9. **报告五段齐备**：逐字稿 / 命中表 / 阶段性结论 / 待复核清单 / 覆盖说明五段均存在。
10. **配置可审计**：`validate_audit_config()` 通过；报告附本次**实际启用类型清单**与 `config_version`；`validate_enabled_types_declared()` 通过。
11. **证据逐字可回溯**：每条命中的 `evidence_text` 均通过 `validate_evidence_traceable()`；被标记 `⚠️[证据不可回溯]` 的条目一律进待复核清单，不得当结论。
12. **判定覆盖如实**：`unjudged_windows` 为空，或已在覆盖说明中显式列出未判定窗口；`validate_judge_coverage()` 通过。
13. **拒收计数披露**：`summary.rejected.*`（unknown_type / timestamp_not_found / evidence_not_verbatim / malformed_hit / illegal_risk_level / duplicated）**原貌写入报告**，不得隐藏被拦截的幻觉命中。

## 适用场景

- 直播回放的全类型违规语义审核（TikTok Shop 达人及内容规则白皮书 27 类）。
- 材质造假（假 14K / 假真金 / 假防水）与品牌授权、假货仿冒的专项审核。
- 需要产出完整逐字稿 + 可取证命中表 + 飞书审核报告的合规质检。
- 长时长回放（10 小时以上）需要分段推进、断点续跑、分批落盘的场景。
- 只跑部分违规类型的定向复审（`--types`）。

## 语义判定架构（v2.0）

```
逐字稿（HH:MM:SS 绝对时间戳）
   ↓  滑窗切分（默认 24 行/窗，overlap 3 行，防跨窗漏检）
【语义违规判定器 semantic_violation_judge.py】
   ↓  读 references/audit_config.yaml（只有 judge_prompt，没有关键词库）
   ↓  对每个窗口，按 enabled 的违规类型批量送大模型语义判断
   ↓  强制 JSON 输出：类型 / 时间戳 / 原文证据 / 风险等级 / 需否人工复核 / 判定理由
【零信任证据回溯断言】证据原文必须能在逐字稿中物理定位，否则判定为幻觉并隔离
   ↓
hits.json + hits.csv → 飞书五段报告
```

**扩展一类新违规 = 在 `audit_config.yaml` 里加一个 block**（id / name / enabled / modality /
force_human_review / judge_prompt / risk_rubric），不需要改任何脚本。反过来，把判定规则硬编码进
`.py` 就破坏了「审核口径可审计」——规则改了没人看得见，这是本技能明确禁止的。

**overlap 为什么必要**：语义常跨行分布（窗尾说「这个是 14K」，下一窗开头说「真金实心」）。
窗口硬切会把这类叠加语义拆散，导致本该判高风险的命中降级或漏掉。

**legacy 关键词通道**：`scripts/risk_keyword_scanner.py` + `references/{material,brand}_risk_keywords.yaml`
**保留但已不是主链路**，降级为「可选召回补充器」，用于与语义判定做双通道交叉对账（语义漏检兜底）。
它只覆盖材质 / 品牌两类，不要拿它的结果冒充全类型审核结论。

## 违规类型注册表（27 类）

来源：TikTok Shop 达人及内容规则白皮书 2.2（2026-06-30）。完整判定标准见
[audit_config.yaml](references/audit_config.yaml)。

| # | id | 中文名 | modality | 默认 enabled | 强制人工复核 |
|---|---|---|---|---|---|
| 1 | `material_fraud` | 材质造假宣称 | audio | ✅ | |
| 2 | `brand_authorization` | 品牌授权与正品宣称 | audio | ✅ | ⚠️ |
| 3 | `counterfeit` | 假货与仿冒品 | audio | ✅ | ⚠️ |
| 4 | `product_attribute_mismatch` | 商品属性不准确（货不对板） | audio+visual | ✅ | |
| 5 | `misleading_pricing` | 商品定价模糊与虚假定价 | audio | ✅ | |
| 6 | `misleading_discount` | 误导性折扣内容 | audio | ✅ | |
| 7 | `exaggerated_absolute_claims` | 夸大宣传与绝对化用语 | audio | ✅ | |
| 8 | `medical_efficacy_claims` | 医疗功效与疾病宣称 | audio | ✅ | |
| 9 | `weight_management_claims` | 体重管理声明 | audio | ✅ | |
| 10 | `sexual_wellness_promotion` | 性健康与私密护理产品推广 | audio | ✅ | ⚠️ |
| 11 | `prohibited_restricted_goods` | 禁限售商品推广 | audio | ✅ | ⚠️ |
| 12 | `gambling_and_gamified` | 赌博与类赌博玩法 | audio | ✅ | |
| 13 | `giveaway_promotion_violation` | 赠品与促销违规 | audio | ✅ | |
| 14 | `auction_violation` | 拍卖违规 | audio | ❌ | |
| 15 | `off_platform_diversion` | 诱导站外引流 | audio | ✅ | |
| 16 | `fraud_traffic_manipulation` | 欺诈、刷单与冒充行为 | audio | ✅ | ⚠️ |
| 17 | `malicious_comparison` | 恶意比较与贬低竞品 | audio | ✅ | |
| 18 | `charity_claims` | 慈善捐赠声明 | audio | ✅ | ⚠️ |
| 19 | `ip_portrait_infringement` | 知识产权与肖像权侵权 | audio+visual | ✅ | ⚠️ |
| 20 | `non_original_content` | 非原创内容（AI 配音/录播） | audio | ✅ | ⚠️ |
| 21 | `aigc_misuse_and_disclosure` | AIGC 滥用与披露缺失 | audio+visual | ✅ | ⚠️ |
| 22 | `minor_involvement` | 涉未成年人内容 | audio+visual | ✅ | ⚠️ |
| 23 | `nudity_sexual_suggestive` | 裸露与性暗示行为 | audio+visual | ✅ | ⚠️ |
| 24 | `shocking_offensive_content` | 耸人听闻与粗俗冒犯言论 | audio | ✅ | |
| 25 | `irrelevant_promotion` | 不相关推广内容 | audio | ✅ | |
| 26 | `before_after_comparison` | 前后效果对比展示 | audio+visual | ✅ | ⚠️ |
| 27 | `static_content` | 静态画面内容 | **visual** | ❌ | ⚠️ |

> **当前默认启用 25 / 27**。未启用：`static_content`（纯视觉维度，ASR-only 链路判不了）、
> `auction_violation`（**拍卖类按用户 2026-08-21 指令暂不纳入审核范围**；条目与 `judge_prompt`
> 全部保留，恢复只需把 `enabled` 改回 `true`）。

**开关口径**：

- `enabled: true/false` 按需开关；`--types a,b,c` 可临时覆盖 `enabled` 做定向复审。
- **`modality: visual` 的类型默认关闭**（目前只有 `static_content`）：ASR-only 链路拿不到画面帧，
  强行开启只会让模型凭空编造「画面静止」，产出的是幻觉不是审核结论。仅在确实提供画面帧采样输入时才开。
- **`modality: audio+visual` 的类型默认开启但强制人工复核**：逐字稿只能判语言层面的信号，
  最终定性必须看视频。把这类命中直接写进「已确认结论」是 Red Flag。
- **`force_human_review: true`（13 类）**：这些类型要么有 ASR 同音误识别高风险（如 `official` ←「老主顾」），
  要么需要联查商品页 / 画面。判定器会强制覆盖模型给的 `need_human_review=false`。

## 三种运行模式

| 模式 | 何时用 | 行为 |
|---|---|---|
| `llm`（默认） | 常规自动判定 | 调 llmproxy 逐窗判定，指数退避重试 |
| `manifest` | TPM 限流 / 断网 / 需要人来判 | 不调 API，把每窗的判定包写成 `packet_<seq>.json`，交由 Agent 语义判定 |
| `ingest` | manifest 的回收环节 | 读回 `packet_<seq>.answer.json`，跑**完全同一套**校验后合并 |

**TPM 限流兜底策略**：llmproxy 端点会间歇性返回 `400` 外壳包内层
`429 RateLimitExceeded.EndpointTPMExceeded`。判定器默认 5 次指数退避重试（base 4s，上限 60s，带 jitter）。
**重试耗尽不允许静默丢窗口**——该窗口进 `unjudged_windows`，最终输出打 `⚠️[窗口未判定]`，
进程以非 0 退出码收尾提示人工介入。限流持续时切 `manifest` 模式走 Agent-in-the-loop，
结果优先，不要干等限流恢复。

`ingest` 与 `llm` 共用同一套零信任后处理函数，禁止两套标准——否则「人判的」就会比「机器判的」宽松，
这正是幻觉最容易溜进结论的缝隙。

## SOP

### 1. 视频摄入策略

目标平台：Pearl（`pearl.tiktok-row.net`）、TikTok。

1. 首选用 `user_skills/yt-dlp-media-downloader` 对**页面 URL** 做 `probe`。
2. 若报 `Unsupported URL`，从页面中抓取 **HLS m3u8 地址**，用 m3u8 重新 probe。这是 Pearl 场景的主路径——回放页本身不被 extractor 识别，但 m3u8 可直取。
3. **内置字幕探查**：检查 `video.textTracks`。为空即说明平台没有内置 Transcript，必须**排除**字幕路径，完全依赖音频 ASR；不要反复尝试拉字幕浪费时间。
4. **音频抽取以 60 秒为单位分段**输出 WAV。长段会同时带来 ASR 超时和时间戳漂移，60 秒是实战验证过的安全上限。
5. **尾段判定**：若某段（常见于最后 3–4 分钟）物理抽取得到**空 WAV**，判定为"回放无有效音频"，记录说明，**不算漏跑**——但必须在报告第 ⑤ 段覆盖说明中显式写出，否则等于隐瞒覆盖缺口。

### 2. ASR 转写规范

- 每段 60 秒，逐段 ASR 后**立即**追加写入本地 Markdown 逐字稿（防止长任务中断丢结果）。
- 时间戳格式 `HH:MM:SS`，且必须是**回放绝对偏移**。片段内相对偏移会让命中无法回溯，取证直接作废。
- 每完成一批片段（建议 5–10 段）立即写回飞书，并做 **RAW 回捞校验**。
- **未 RAW 校验绝不汇报"已更新 / 已完成"**。

### 3. 语义违规判定

```bash
cd user_skills/live-material-fraud-auditor
python3 scripts/semantic_violation_judge.py \
  --transcript <逐字稿.md> --out-json hits.json --out-csv hits.csv
```

- 判定前先过 `validate_audit_config()`（`audit_guard.py --check config`），配置烂了后面全是幻觉。
- 默认跑全部 `enabled: true` 的 25 类；`--types` 可定向复审。
- 长任务加 `--resume`，断点落 `temp_data/judge_progress.json`。
- 退出码：`0` 全窗判定完成；`3` 存在 `unjudged_windows`（禁止宣称全量完成）；`2` 链路硬失败。

### 4. 零信任后处理（反幻觉核心）

模型返回的每条命中按顺序过 7 道闸门，任一失败即隔离而非静默通过：

| # | 闸门 | 失败处置 |
|---|---|---|
| 1 | 类型白名单 | 丢弃，计入 `rejected.unknown_type` |
| 2 | 时间戳存在性 | 丢弃，计入 `rejected.timestamp_not_found` |
| 3 | **证据逐字可回溯** | 保留但打 `⚠️[证据不可回溯]` + 强制人工复核，计入 `rejected.evidence_not_verbatim` |
| 4 | 风险等级白名单 | 降级为 `中` + 强制人工复核 |
| 5 | 强制人工复核注入 | `force_human_review` 类型 / `confidence < 0.7` 一律覆盖为 true |
| 6 | 重叠窗口去重 | 同 (类型, 时间戳, 归一化证据) 保留 confidence 最高者 |
| 7 | 统计口径输出 | `rejected.*` **原貌输出**，禁止藏起来 |

第 3 道是整条链路的地基：证据归一化（NFKC 统一全半角 + 去空白 + 小写）后必须是窗口逐字稿的子串。
只抹掉排版差异，**不允许任何语义改写通过**——模型把没说过的话总结成像是说过的，正是幻觉的典型形态。
被标记不可回溯的条目**绝不允许当作已确认命中输出**。

### 5. 风险分级

统一为 `高 / 中 / 低` 三级，每类的分级标准写在 `audit_config.yaml` 的 `risk_rubric` 里，
由模型按 rubric 判定。跨类通则：

- **高**：明确、无限定、直接影响购买决策或触及平台红线的宣称。
- **中**：单点出现的绝对化表述、隐瞒关键条件、暗示性规避表述。
- **低**：带限定词、有澄清、或仅属表述不严谨。

### 6. ASR 误识别与人工复核

- 中文口语「老主顾 / 老顾客」可能被 ASR 误转写为 `official`；英文 `all the shows` / `a fisher` 同理。
  `brand_authorization` 因此设为 `force_human_review: true`。
- 疑似项**不得**作为已确认事实纳入审核结论，单独列入「待复核清单」。
- 脚本只做**召回与熔断**，不做最终定性。

### 7. 飞书报告结构（固定五段）

① 全量逐字稿
② 取证命中表：`违规类型 | 时间戳 | 原文证据 | 风险等级 | 需人工复核 | 判定理由`
③ 阶段性审核结论（附本次启用类型清单 + `config_version`）
④ 待人工复核清单（含所有 `⚠️[证据不可回溯]` 与 `audio+visual` 类命中）
⑤ 覆盖说明（含尾段空 WAV 情况、`unjudged_windows`、`rejected.*` 拒收计数）

写入**必须**调用 `user_skills/feishu-doc-writing-guide`（禁止裸调 lark MCP / 禁止 OpenAPI 直连），每次写入后做 RAW 回捞校验。

### 8. 断点续跑机制

- ASR / 飞书写回断点：`temp_data/progress.json`（v1.x 沿用，含 `revision_id` + 已覆盖区间）。
- 语义判定断点：`temp_data/judge_progress.json`（含 `last_done_window_seq` / `judged_windows` / `unjudged_windows`）。
  两者并存不冲突。
- 续跑时从最新**RAW 校验通过**的断点继续，不重跑已完成区间。
- 汇报时如实告知真实覆盖范围，**禁止虚报全量完成**。

### 9. 最终判定输出格式

```
本次启用类型：25 / 27（未启用：static_content、auction_violation）
配置版本：config_version=2.0

各类风险：
  material_fraud        🔴 高    XX 条
  counterfeit           🔴 高    XX 条
  brand_authorization   🟡 中    XX 条
  ...（仅列出有命中的类型）

总命中条数：XX 条
待人工复核：XX 条（其中证据不可回溯 XX 条）
拒收统计：unknown_type=X / timestamp_not_found=X / evidence_not_verbatim=X /
         malformed_hit=X / illegal_risk_level=X / duplicated=X
判定覆盖：XX / XX 窗口（unjudged_windows=[]）
```

## 脚本用法

所有脚本必须通过 `bash` 工具直接执行；涉及飞书回读或 llmproxy 调用时设置 `include_secrets=true`
（判定器从环境变量 `AIME_USER_CLOUD_JWT` 取 Bearer）。

**语义违规判定（主链路）**：

```bash
cd user_skills/live-material-fraud-auditor

# 自动判定
python3 scripts/semantic_violation_judge.py --transcript t.md --out-json hits.json --out-csv hits.csv

# 定向复审 + 断点续跑
python3 scripts/semantic_violation_judge.py --transcript t.md --types counterfeit,material_fraud --resume

# 限流兜底：导出判定包 -> Agent 判定 -> 回收
python3 scripts/semantic_violation_judge.py --transcript t.md --mode manifest --packet-dir pk/
python3 scripts/semantic_violation_judge.py --transcript t.md --mode ingest --packet-dir pk/ --out-json hits.json

# 自检（全程 mock，不打真实 API）
python3 scripts/semantic_violation_judge.py --self-test
```

**运行时护栏（副作用前物理熔断）**：

```bash
python3 scripts/audit_guard.py --self-test
```

| 函数 | 熔断条件 |
|---|---|
| `validate_segment_duration()` | 单段音频 > 60 秒 |
| `validate_timestamp_absolute()` | 时间戳非绝对偏移 / 非 `HH:MM:SS` / 倒退 |
| `assert_raw_readback()` | 写入飞书后回读内容与预期不一致 |
| `validate_coverage_report()` | 覆盖说明缺失实际区间 / 总时长 / 尾段空 WAV 说明 |
| `validate_hit_row()` | 关键词命中行缺时间戳 / 原文 / 类别 / 等级（legacy 通道） |
| `validate_progress_checkpoint()` | 断点文件缺 `revision_id` 或已覆盖区间 |
| `validate_audit_config()` | 配置缺 section / 类型缺字段 / id 重复 / rubric 键非法 |
| `validate_semantic_hit_row()` | 语义命中行六要素缺任一项 |
| `validate_evidence_traceable()` | 证据归一化后不是逐字稿子串（反幻觉） |
| `validate_enabled_types_declared()` | 报告出现本次未启用的违规类型 |
| `validate_judge_coverage()` | 有 `unjudged_windows` 却宣称全量判定完成 / 窗口账目对不上 |

CLI 单点校验示例：

```bash
python3 scripts/audit_guard.py --check config --config-file references/audit_config.yaml
python3 scripts/audit_guard.py --check evidence --transcript-file t.md --evidence "<原文片段>"
python3 scripts/audit_guard.py --check judge-coverage --summary-json hits.json
python3 scripts/audit_guard.py --check segment --seconds 75          # 预期熔断
```

**legacy 关键词召回（漏检兜底，非主链路）**：

```bash
python3 scripts/risk_keyword_scanner.py --transcript t.md --out-json legacy_hits.json
```

## 合规默认值（Defaults）

- 默认审核配置：`references/audit_config.yaml`（`config_version=2.0`，27 类注册 / 25 类默认启用；未启用：static_content、auction_violation）
- 默认判定模型：`doubao-seed-2.0-lite-user`（llmproxy 当前唯一放行模型）
- 默认 llmproxy 端点：`https://aime.bytedance.net/api/agents/v2/llmproxy/user/chat/completions`（body 用 `max_tokens`，`temperature=0`）
- 默认窗口：**24 行 / 窗，overlap 3 行**
- 默认重试：**5 次指数退避**（base 4s，上限 60s，带 jitter）
- 默认低置信阈值：`confidence < 0.7` 强制人工复核
- 默认语义判定断点：`temp_data/judge_progress.json`
- 默认分段时长：**60 秒**（`DEFAULT_SEGMENT_SECONDS`）
- 默认时间戳格式：`HH:MM:SS` 绝对偏移
- 默认批次大小：**5–10 段**（`DEFAULT_BATCH_SEGMENTS = 8`）
- 默认写后等待：**2 秒**再回读
- 默认飞书写入通道：`user_skills/feishu-doc-writing-guide`
- 默认摄入通道：`user_skills/yt-dlp-media-downloader`
- 默认 ASR / 写回断点：`temp_data/progress.json`
- 默认报告段数：5

## 约束条件

- 摄入、转写、判定、写入四段都以"可回读证据"为交付标准，命令退出码 0 不等于成功。
- **审核口径外化在 `references/audit_config.yaml`**，新增或调整违规类型请改 YAML 而不是改脚本，保证口径可审计、可 diff。
- 脚本只做**召回与熔断**，不做最终定性；`audio+visual` 类与 `force_human_review` 类一律需要人工确认。
- 长任务必须分批 + 断点，单次尝试覆盖全部时长会在中断时丢失全部上下文。
- 限流不是跳过窗口的理由：要么退避重试，要么切 `manifest` 模式让人判，要么如实上报 `unjudged_windows`。

## 📖 案例实录 (Best Practice)

- 🧑‍💻 用户输入：

```text
帮我审核这场 Pearl 直播回放，按 TikTok Shop 规则全类型过一遍：roomId=7667566803098323734（GB 市场）
```

- 🤖 标准输出：

```text
1. yt-dlp probe 页面 URL 失败（Unsupported URL），改用页面 HLS m3u8 重新 probe 成功；
   textTracks 为空 → 排除内置字幕，走音频 ASR。
2. 按 60 秒切片抽 WAV，逐段 ASR 并即时追加逐字稿；末段 3–4 分钟抽出空 WAV，记为"回放无有效音频"。
3. 实际有效覆盖 00:00:00–20:16:10（总时长 20:19:52）。
4. audit_guard.py --check config 通过（config_version=2.0，启用 25/27 类；未启用 static_content、auction_violation）。
5. semantic_violation_judge.py 滑窗 24 行/overlap 3 判定；期间遇 429 限流，退避重试后 3 个窗口仍失败，
   切 manifest 模式由 Agent 补判后 ingest 回收，最终 unjudged_windows=[]。
6. 命中：material_fraud 高 42 条、counterfeit 高 6 条、brand_authorization 中 8 条、
   off_platform_diversion 高 3 条、misleading_pricing 中 11 条。
   拒收：evidence_not_verbatim=4（已标 ⚠️[证据不可回溯] 并入待复核）、unknown_type=1。
7. 五段结构写入飞书审核报告并逐批 RAW 回捞校验通过；启用类型清单与拒收计数原貌写入第 ③⑤ 段。
```

v1.x 实战记录见 [pearl-case-2026-08.md](references/pearl-case-2026-08.md)。

## 更新日志 (Changelog)

- **2.1（2026-08-21）**：按用户指令收窄审核范围 —— 拍卖类不纳入当前审核。
  - `references/audit_config.yaml` 中 `auction_violation` 的 `enabled` 由 `true` 改为 `false`，
    并在条目注释中标注关闭原因与恢复方式。**采用「设为 false」而非物理移除**：可逆，且保留白皮书条款溯源；
    `judge_prompt` / `risk_rubric` / `id` 一律未改，其余 26 类 enabled 状态不动。
  - 默认启用口径由 **26 / 27 收窄为 25 / 27**，禁用集合变为 `{static_content, auction_violation}`；
    SKILL.md 注册表、Defaults、输出格式、案例实录中的硬编码口径全量同步。
  - `scripts/semantic_violation_judge.py` 与 `scripts/audit_guard.py` 新增常量
    `REGISTERED_VIOLATION_TYPE_COUNT` / `EXPECTED_DISABLED_TYPE_IDS` / `EXPECTED_ENABLED_TYPE_COUNT`，
    并在两处 `--self-test` 中新增「禁用集合 == {static_content, auction_violation}」与
    「启用数 == 25」的物理断言 —— 口径再漂移会直接 self-test 失败，而不是静默跑偏。
- **2.0（2026-08-21）**：架构升级为 prompt-driven 语义判定。
  - **语义判定取代关键词库**：新增 `scripts/semantic_violation_judge.py` 作为主链路；
    每类违规只用一段自然语言 `judge_prompt`，抗「换个说法就漏」的规避，扩展新类型无需改脚本。
  - **27 类违规注册表**：依据 TikTok Shop 达人及内容规则白皮书 2.2（2026-06-30）落地
    `references/audit_config.yaml`，覆盖误导性内容、健康类、禁限售、高风险行为、误导行为、
    AIGC、平台内容要求、低质量内容等全部违规族；**新增 `counterfeit`（假货/仿冒品）**。
  - **三种运行模式**：`llm`（自动）/ `manifest`（Agent-in-the-loop 降级）/ `ingest`（回收），
    应对 llmproxy `429 RateLimitExceeded.EndpointTPMExceeded` 限流；重试耗尽不静默丢窗口，
    进 `unjudged_windows` 并以非 0 退出码收尾。
  - **反幻觉证据回溯断言**：7 道零信任后处理闸门，核心是 `evidence_text` 归一化后必须是
    逐字稿子串；不可回溯的条目打 `⚠️[证据不可回溯]` 并强制人工复核，绝不当已确认命中。
    `rejected.*` 拒收计数原貌输出。
  - **`audit_guard.py` 新增 5 个 L3 gate**：`validate_audit_config` / `validate_semantic_hit_row` /
    `validate_evidence_traceable` / `validate_enabled_types_declared` / `validate_judge_coverage`，
    v1.x 六个旧 gate 全部保留。
  - **legacy 关键词通道降级保留**：`risk_keyword_scanner.py` 与两个词库 yaml 不删除，
    降级为语义漏检的双通道交叉对账兜底。
  - **v1.x 架构完全兼容**：60 秒分段 ASR、`HH:MM:SS` 绝对时间戳、RAW 回捞、断点续跑、
    飞书五段报告结构全部保持不变；第 ② 段命中表列头升级为六列。
  - Verification 新增第 10–13 条；Common Rationalizations / Red Flags 同步加固。
- 1.1（2026-08-21）：首版发布。固化 Pearl 20 小时回放实战经验：m3u8 降级 probe、60 秒切片 ASR、绝对时间戳、材质/品牌双词库与邻近 3 句升级规则、ASR 误识别隔离、五段报告结构、RAW 回读与断点续跑；配套 `risk_keyword_scanner.py`（命中召回）与 `audit_guard.py`（L3 运行时熔断）。

## ☁️ 云端发布记录

- `cloud_publish_status`: **SUCCESS**
- `skill_name`: `live-material-fraud-auditor`
- `version`: `2.1`
- `cloud_scope`: `user`
- `cloud_published_at`: `2026-08-21 20:48`
- `cloud_skill_id`: `92c6fb61-607c-4073-8bdd-9e7172fa27bc`
