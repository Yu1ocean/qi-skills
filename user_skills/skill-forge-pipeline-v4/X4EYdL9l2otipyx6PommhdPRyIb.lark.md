<title>live-material-fraud-auditor · 直播材质造假与品牌授权审核员 v1.1</title>

<figure view-type="Card"><source name="live-material-fraud-auditor.zip" href="https://internal-api-drive-stream.feishu.cn/space/api/box/stream/download/authcode/?code=N2FlZjg0NWUxMDMzOGVjZjI2Y2ExZmE5MjBmOWIxOTlfMGQ4ZmZiNjFiOTAzZjNlNTFiZGRmYzQ1ZmQ0YjNhMWFfSUQ6NzY3NjQyNjI1MTQ2MTYxMTEyNV8xNzg3MzA3MjczOjE3ODczMTA4NzNfVjM" mime="application/zip" size="20941" token="EZHhba90KoBTVaxwvlpm3thOynf"/></figure>

<callout emoji="📌">
**Skill ID**：LIVE-MATERIAL-FRAUD-AUDITOR ｜ **版本**：v1.1 ｜ **作者**：于奇楠（yuqinan）
**技能目录**：user_skills/live-material-fraud-auditor
**CDA 三层护栏自检**：PASSED（risk=high，L1 + L2 + L3 齐备）
</callout>

# 📌 技能简介

对 TikTok / Pearl 等平台的**直播回放**做「材质造假」（假 14K、假真金、假防水）与「品牌授权 / 正品宣称」的合规审核，产出**可取证**的三件套：全量逐字稿、风险命中表、飞书审核报告。

审核对象是「主播**说了什么**」，而不是「商品页写了什么」，因此整条链路的可信度完全建立在三件事上：**音频被完整摄入**、**时间戳绝对准确**、**命中可回溯**。技能内所有护栏都是为了让这三件事不被「看起来完成了」糊过去。

本技能固化自 2026-08 Pearl 平台一场 **20 小时直播回放**的实战审核（GB 市场，总时长 20:19:52，有效覆盖 00:00:00–20:16:10，命中材质高风险 75+ 条、品牌 / 正品 8+ 条）。

# 🔑 触发词

- 核心关键词：    

  - 直播材质审核
  - 材质造假审核
  - 直播合规审核
  - live-material-fraud-auditor
  - 假 14K / 假真金 / 假防水
  - 品牌授权宣称 / 正品宣称
- 典型指令示例：

> 帮我审核这场直播回放有没有材质造假（假 14K、假真金）和品牌授权问题
> 
> 这个 Pearl 回放 roomId=xxx，做一遍直播合规审核并出飞书报告

# ⚙️ 核心架构 / SOP / 约束条件

## 一、九步 SOP 总览

| # | 阶段 | 关键动作与硬约束 |
|-|-|-|
| 1 | 视频摄入策略 | 先用 `yt-dlp-media-downloader` probe **页面 URL**；报 `Unsupported URL` 时改抓页面内 **HLS m3u8** 重新 probe（Pearl 主路径）。检查 `video.textTracks`，为空即排除字幕路径。音频按 **60 秒**切片输出 WAV。尾段空 WAV 判为「回放无有效音频」，不算漏跑但必须写进覆盖说明。 |
| 2 | ASR 转写规范 | 逐段 ASR 后**立即**追加写入本地 Markdown；时间戳必须是 `HH:MM:SS`**回放绝对偏移**；每 5–10 段写回飞书并做 RAW 回捞；未 RAW 校验绝不汇报「已完成」。 |
| 3 | 材质风险词库 | 纯度标记 / 真金宣称 / 防水不变色 / 使用场景 / 物理强度 / 检测背书 六组，外化在 `references/material_risk_keywords.yaml`。 |
| 4 | 品牌风险词库 | 授权类 + 奢侈品牌名，外化在 `references/brand_risk_keywords.yaml`；与材质组件在**同句或近邻 3 句**内组合出现即升级。 |
| 5 | 风险分级判定 | 见下方分级表。 |
| 6 | ASR 误识别处理 | 疑似命中标注「需人工回听」，**不得**作为已确认事实进入结论，单独进「待复核清单」。 |
| 7 | 飞书报告结构 | 固定五段：① 全量逐字稿 ② 取证命中表 ③ 阶段性结论 ④ 待人工复核清单 ⑤ 覆盖说明。写入必须走 `feishu-doc-writing-guide`。 |
| 8 | 断点续跑 | 每次写回后记录最新 `revision_id` + 已覆盖区间到 `temp_data/progress.json`；只从 **RAW 校验通过**的断点续跑。 |
| 9 | 最终判定输出 | 材质风险等级 / 品牌风险等级 / 总命中条数 / 待复核条数。 |

## 二、风险分级判定标准

| 等级 | 判定条件 |
|-|-|
| 🔴 高（材质造假） | `real gold plated` + `14K stamp` 叠加，且无明显「镀金」澄清 |
| 🟡 中-高（品牌宣称） | `official` / `authorized` / `genuine` 单独出现 → 需联查挂车商品标题、详情页、包装、评论后定级 |
| 🔴 高（误导性背书） | `pass diamond test` / `magnetic test` + 实心 / 真金宣称 |

<callout emoji="❗">
**ASR 误识别真实案例**：中文口语「老主顾」被 ASR 误识别为 `official`。若直接采信，就等于凭空造出一条品牌宣称风险。此类命中一律打 `need_human_review=true`，只进待复核清单，不进结论。
</callout>

## 三、CDA 三层护栏（risk=high，L1 + L2 + L3 齐备）

| 层级 | 形态 | 落地内容 |
|-|-|-|
| L1 认知层 | 反合理化三件套 | `SKILL.md` 顶置 Common Rationalizations（8 条借口）/ Red Flags（9 条危险信号）/ Verification（9 条强制验收） |
| L2 默认层 | 合规默认值 | 分段 60 秒、时间戳 `HH:MM:SS` 绝对偏移、邻近窗口 3 句、批次 8 段、写后等待 2 秒、写入通道锁定 `feishu-doc-writing-guide`、摄入通道锁定 `yt-dlp-media-downloader` |
| L3 断言层 | 运行时物理熔断 | `scripts/audit_guard.py` 提供 6 道 gate，失败一律 `raise AuditGuardError`，绝不返回 False 让调用方自行决定 |

## 四、脚本与运行时闸门

**1）风险关键词扫描器（命中召回）**

```bash
cd user_skills/live-material-fraud-auditor
python3 scripts/risk_keyword_scanner.py --transcript transcript.md \
  --out-json hits.json --out-csv hits.csv

# 内置自检（含 4 条规则正例 + 相对时间戳负例）
python3 scripts/risk_keyword_scanner.py --self-test
```

输出字段：`timestamp / seconds / text / category / risk_level / matched_keywords / groups / rule / need_human_review / review_reason / neighbor_window`。所有行落盘前都过 `validate_hit_row()`，四要素缺一即熔断。

**2）运行时护栏（副作用前物理熔断）**

| 函数 | 熔断条件 |
|-|-|
| `validate_segment_duration()` | 单段音频 > 60 秒 |
| `validate_timestamp_absolute()` | 时间戳非绝对偏移 / 非 `HH:MM:SS` / 倒退 |
| `assert_raw_readback()` | 写入飞书后回读内容与预期不一致 |
| `validate_coverage_report()` | 覆盖说明缺失实际区间、总时长或尾段空 WAV 说明 |
| `validate_hit_row()` | 命中行缺少时间戳 / 原文 / 类别 / 等级 |
| `validate_progress_checkpoint()` | 断点文件缺 `revision_id`、区间非法或未 RAW 校验 |

```bash
# 全量自检
python3 scripts/audit_guard.py --self-test

# 单点校验
python3 scripts/audit_guard.py --check segment --seconds 75          # 预期熔断
python3 scripts/audit_guard.py --check coverage --coverage-file coverage.md
python3 scripts/audit_guard.py --check hits --hits-json hits.json
```

## 五、约束条件

- 摄入、转写、写入三段都以「可回读证据」为交付标准，**命令退出码 0 不等于成功**。
- 关键词库外化在 `references/*.yaml`，新增词只改 YAML 不改脚本，保证审核口径可审计。
- 脚本只做**召回与熔断**，不做定性；🟡 中-高 一律需要联查商品页并人工确认。
- 长任务必须分批 + 断点，单次尝试覆盖全部时长会在中断时丢失全部上下文。
- 禁止绕过 `feishu-doc-writing-guide` 裸调飞书 OpenAPI / lark MCP 直写文档。
- 禁止虚报覆盖范围：汇报覆盖区间必须 ≤ 实际 RAW 校验通过的区间。

# 📖 案例实录 (Best Practice)

**🧑‍💻 用户输入**

```text
帮我审核这场 Pearl 直播回放有没有材质造假和品牌授权问题：roomId=7667566803098323734（GB 市场）
```

**🤖 标准输出**

```text
1. yt-dlp probe 页面 URL 失败（Unsupported URL），改用页面 HLS m3u8 重新 probe 成功；
   video.textTracks 为空 -> 排除内置字幕路径，完全走音频 ASR。
2. 按 60 秒切片抽 WAV，逐段 ASR 并即时追加逐字稿；
   末段 3-4 分钟抽出空 WAV，记为「回放无有效音频」，写入覆盖说明。
3. 实际有效覆盖 00:00:00-20:16:10（总时长 20:19:52）。
4. risk_keyword_scanner.py 命中材质高风险 75+ 条、品牌/正品 8+ 条；
   「老主顾」被误识别为 official 的条目已打 need_human_review，仅进待复核清单。
5. 五段结构写入飞书审核报告，每批写入后 RAW 回捞校验通过。

最终判定：
  材质宣传风险：🔴 高
  品牌/正品宣称风险：🟡 中-高（需联查挂车商品标题/详情页/包装/评论）
  总命中条数：83+ 条（材质 75+ / 品牌 8+）
```

---

# 更新日志

- **v1.1（2026-08-21）首版发布**：固化 Pearl 20 小时回放实战经验——m3u8 降级 probe、60 秒切片 ASR、绝对时间戳、材质 / 品牌双词库与近邻 3 句升级规则、ASR 误识别隔离、五段报告结构、RAW 回读与断点续跑；配套 `risk_keyword_scanner.py`（命中召回）与 `audit_guard.py`（6 道 L3 运行时熔断）。CDA 自检 PASSED（risk=high）。