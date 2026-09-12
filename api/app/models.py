"""请求结构模型（Pydantic v2）。

结构性约束（取值范围、字段是否多余等）交给 Pydantic；
起点/出口与阻挡格之间的语义关系在 ``validation`` 模块中校验。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Cell(BaseModel):
    """网格坐标，[行, 列]，均为 0 基索引。

    严格整数：整值小数（如 3.0）、布尔、数字字符串一律拒绝，
    不做静默转换。
    """

    model_config = ConfigDict(extra="forbid")

    row: StrictInt = Field(..., ge=0, description="行索引（0 基）")
    col: StrictInt = Field(..., ge=0, description="列索引（0 基）")

    def as_tuple(self) -> tuple[int, int]:
        return (self.row, self.col)


class GridPlan(BaseModel):
    """前端提交的完整平面。"""

    model_config = ConfigDict(extra="forbid")

    rows: StrictInt = Field(..., ge=2, le=40, description="行数（2-40）")
    cols: StrictInt = Field(..., ge=2, le=40, description="列数（2-40）")
    start: Cell
    exit: Cell
    blocked: list[Cell] = Field(default_factory=list)
    # 省略与空列表等价：无费力格时退化为原四方向 BFS；
    # 但显式传 null 属于类型错误，必须拒绝。
    # 使用别名 difficultCells 作为对外 JSON 字段名。
    difficult_cells: list[Cell] = Field(
        default_factory=list, alias="difficultCells", description="费力通行格（进入代价为 3）"
    )
