# Changelog — weekly-top3-patrol

## v1.4 — 2026-06-08 (安全与渲染修复)

### 修复

- 统一真实入口为 `scripts/patrol.py`，`run_patrol.py` 降级为兼容转发包装器，并在 stderr 明示废弃。
- Mode B 新增周度幂等锁，基于 `logs/patrol_<YYYY_WW>.json` 避免同周对同一人重复建会。
- 新增 `--confirm-real-send` 硬门禁；任何非 dry-run 的真实群发 / 日历写入，未显式确认即熔断。
- 修复 `build_l0_card`：Mode B 的强插日程列表改为“姓名：时间段”绑定展示，不再只显示时间段。
- 增补 `tests/test_patrol_guards.py`，覆盖真实发送门禁、周度幂等锁与卡片渲染。

## v1.1 — 2026-05-25 (首次锻造发布)

### 新增

- 双模式核心引擎：
  - Mode A (Sunday 16:00) — 软性催办，群内 @ 未填同学。
  - Mode B (Monday 16:00) — 硬性收口，调用 freebusy 找共同空闲交集，自动强插 15min 1on1。
- **代码层硬过滤**：`scripts/exemption_filter.py` 永久豁免 `jiaoyanchen@bytedance.com`，含 L3 运行时 `assert_exemption_invariant`。
- **CHAT_REGISTRY SSOT**：`scripts/chat_registry_loader.py` 从 `CHAT_REGISTRY.json` 单一真相源读取群 ID，并做群名关键字断言（`UK/EU/JP POP BD`）。
- **共同空闲算法**：`scripts/interval_intersect.py` 实现两人 busy 列表 → 空闲反转 → 交集 → 找 ≥15min 首个 slot。
- **三层护栏自检**：`scripts/selfcheck.py` 一键校验 L1/L2/L3。
- **测试套件**：`tests/test_exemption_filter.py` 覆盖豁免名单 7 项断言。
- **Schedule cron 配置建议**：`references/schedule_cron_setup.md`。
- **未填判定规则**：`references/empty_detection_rules.md` 三选一标准。

### 风险与边界

- **风险等级**：High（涉及群内 @ 广播 + 日历强插写操作 + Bitable 读取）
- **首次部署**：必须先 `--dry-run` 一周验证，再切真实路径。
- **失败降级**：Bitable 拉取失败 → DLQ；Calendar 写入失败 → 该用户进 unresolvable，不影响其他人。

## v1.5 — 2026-06-15 (豁免名单更新)

### 变更

- **豁免名单扩容**：`scripts/exemption_filter.py` 新增 Cherry Gao（`gaochuan.cherry@bytedance.com`）与王皓田（`wanghaotian.666@bytedance.com`）两位业务方决议豁免对象。
- **测试覆盖同步**：`tests/test_exemption_filter.py` 为两位新增豁免对象补充 `assert is_exempt(email)` 断言，确保代码层硬过滤可验收。
