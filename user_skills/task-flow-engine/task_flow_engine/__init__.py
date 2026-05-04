"""Task Flow Engine

用于对飞书【任务库】执行“任务追踪 / 巡检 / 催办分流”闭环：
- 每日对账巡查：读取【任务库】，计算 DDL 风险，生成可用于告警分流的“告警词典”
- 休假免打扰与顺延：法定休息日与个人休假拦截器（静默顺延）

边界说明：
- “双轨写入（dual_write）”已迁移至 `heartbeat-inspector`，本包不再负责写表。

该目录是通用 Python 包，可被脚本或其他技能代码 import。
"""

from .patrol import TaskPatrol
from .vacation import FeishuVacationClient, apply_vacation_guard, is_legal_rest_day

__all__ = [
    "TaskPatrol",
    "FeishuVacationClient",
    "apply_vacation_guard",
    "is_legal_rest_day",
]
