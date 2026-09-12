"""通行实测模块的请求结构模型（Pydantic v2）。

实测只能由一次成功的路线核验发起：创建接口只接受核验结果中的有序
坐标快照，不接受整张平面，避免实测与平面后续编辑产生耦合。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .models import Cell

# 单格试走耗时（秒）的允许范围；可选的单段目标秒数沿用同一范围
MIN_SECONDS = 1
MAX_SECONDS = 3600


class WalkTrialCreate(BaseModel):
    """创建一次通行实测的请求体：不可变路线快照 + 可选单段目标秒数。"""

    model_config = ConfigDict(extra="forbid")

    # 起点 → 出口的有序坐标，至少两格；坐标本身允许 0 基任意非负整数
    # （是否越界由路线核验阶段负责，这里只校验“相邻且四方向”）。
    path: list[Cell]

    # 可选的单段目标秒数（1–3600 的整数）：省略（None）表示不判定，
    # 与旧客户端契约一致；提供时用于把每段标记为“超时/达标”。
    # 类型/范围/显式 null 的拒绝在 walk.parse_target_seconds 中完成，
    # 这里的 StrictInt 约束作为落库前的兜底。
    target_seconds: StrictInt | None = Field(
        default=None,
        alias="targetSeconds",
        ge=MIN_SECONDS,
        le=MAX_SECONDS,
        description="可选单段目标秒数（1-3600）",
    )
