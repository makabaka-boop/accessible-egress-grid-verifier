"""通行实测模块的请求结构模型（Pydantic v2）。

实测只能由一次成功的路线核验发起：创建接口只接受核验结果中的有序
坐标快照，不接受整张平面，避免实测与平面后续编辑产生耦合。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .models import Cell

# 单格试走耗时（秒）的允许范围
MIN_SECONDS = 1
MAX_SECONDS = 3600


class WalkTrialCreate(BaseModel):
    """创建一次通行实测的请求体：不可变路线快照。"""

    model_config = ConfigDict(extra="forbid")

    # 起点 → 出口的有序坐标，至少两格；坐标本身允许 0 基任意非负整数
    # （是否越界由路线核验阶段负责，这里只校验“相邻且四方向”）。
    path: list[Cell]
