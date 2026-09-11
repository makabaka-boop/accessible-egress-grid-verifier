"""语义级校验：行列与坐标之间的关系。

结构校验（类型、范围、多余字段）由 Pydantic 完成；
这里只处理“坐标越界 / 起终点重合 / 起终点被阻挡 / 阻挡格重复”。
所有错误一次性收集，返回字段级错误列表。
"""

from __future__ import annotations

from .models import GridPlan

FIELD_LABELS = {
    "rows": "行数",
    "cols": "列数",
    "start": "起点",
    "exit": "出口",
    "blocked": "阻挡格",
}


class SemanticError(Exception):
    """携带字段级错误信息的语义校验失败。"""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__(f"{len(errors)} semantic error(s)")


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def validate_semantics(plan: GridPlan) -> None:
    """校验通过返回 None，否则抛出 :class:`SemanticError`。"""

    errors: list[dict[str, str]] = []

    start = plan.start.as_tuple()
    target = plan.exit.as_tuple()

    if not (0 <= start[0] < plan.rows and 0 <= start[1] < plan.cols):
        errors.append(
            _err(
                "start",
                f"起点坐标 ({start[0]}, {start[1]}) 越界："
                f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
            )
        )
    if not (0 <= target[0] < plan.rows and 0 <= target[1] < plan.cols):
        errors.append(
            _err(
                "exit",
                f"出口坐标 ({target[0]}, {target[1]}) 越界："
                f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
            )
        )

    blocked_coords: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    duplicated: set[tuple[int, int]] = set()
    out_of_bounds: list[tuple[int, int]] = []
    for cell in plan.blocked:
        coord = cell.as_tuple()
        blocked_coords.append(coord)
        if coord in seen:
            duplicated.add(coord)
        seen.add(coord)
        if not (0 <= coord[0] < plan.rows and 0 <= coord[1] < plan.cols):
            out_of_bounds.append(coord)

    for coord in out_of_bounds:
        errors.append(
            _err(
                "blocked",
                f"阻挡格坐标 ({coord[0]}, {coord[1]}) 越界："
                f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
            )
        )
    for coord in sorted(duplicated):
        errors.append(_err("blocked", f"阻挡格 ({coord[0]}, {coord[1]}) 重复出现"))

    blocked_set = set(blocked_coords)
    if start == target:
        errors.append(_err("exit", "出口与起点不能是同一个格"))
    if start in blocked_set:
        errors.append(_err("start", "起点位于阻挡格上，疏散路线无法开始"))
    if target in blocked_set:
        errors.append(_err("exit", "出口位于阻挡格上，无法作为疏散终点"))

    if errors:
        raise SemanticError(errors)
