"""语义级校验：行列与坐标之间的关系。

结构校验（类型、范围、多余字段）由 Pydantic 完成；
这里只处理“坐标越界 / 起终点重合 / 起终点被阻挡 / 阻挡格重复 /
费力格越界、重复或落在起点、出口、阻挡格上”。
所有错误一次性收集，返回字段级错误列表。
"""

from __future__ import annotations

from .models import Cell, GridPlan

FIELD_LABELS = {
    "rows": "行数",
    "cols": "列数",
    "start": "起点",
    "exit": "出口",
    "blocked": "阻挡格",
    "difficultCells": "费力通行格",
}

# 费力格的对外字段路径（与请求 JSON 中的别名一致，可直接定位到索引）
DIFFICULT_FIELD = "difficultCells"


class SemanticError(Exception):
    """携带字段级错误信息的语义校验失败。"""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__(f"{len(errors)} semantic error(s)")


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


def _in_bounds(plan: GridPlan, coord: tuple[int, int]) -> bool:
    return 0 <= coord[0] < plan.rows and 0 <= coord[1] < plan.cols


def validate_semantics(plan: GridPlan) -> None:
    """校验通过返回 None，否则抛出 :class:`SemanticError`。"""

    errors: list[dict[str, str]] = []

    start = plan.start.as_tuple()
    target = plan.exit.as_tuple()
    start_in_bounds = _in_bounds(plan, start)
    target_in_bounds = _in_bounds(plan, target)

    if not start_in_bounds:
        errors.append(
            _err(
                "start",
                f"起点坐标 ({start[0]}, {start[1]}) 越界："
                f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
            )
        )
    if not target_in_bounds:
        errors.append(
            _err(
                "exit",
                f"出口坐标 ({target[0]}, {target[1]}) 越界："
                f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
            )
        )

    # ---- 阻挡格：收集越界/重复（阻挡格错误不定位到索引，沿用 blocked 字段） ----
    blocked_coords: list[tuple[int, int]] = []
    blocked_seen: set[tuple[int, int]] = set()
    blocked_duplicated: set[tuple[int, int]] = set()
    blocked_out_of_bounds: list[tuple[int, int]] = []
    for cell in plan.blocked:
        coord = cell.as_tuple()
        blocked_coords.append(coord)
        if coord in blocked_seen:
            blocked_duplicated.add(coord)
        blocked_seen.add(coord)
        if not _in_bounds(plan, coord):
            blocked_out_of_bounds.append(coord)

    for coord in blocked_out_of_bounds:
        errors.append(
            _err(
                "blocked",
                f"阻挡格坐标 ({coord[0]}, {coord[1]}) 越界："
                f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
            )
        )
    for coord in sorted(blocked_duplicated):
        errors.append(_err("blocked", f"阻挡格 ({coord[0]}, {coord[1]}) 重复出现"))

    blocked_set = set(c for c in blocked_coords if _in_bounds(plan, c))

    # ---- 费力格：越界/重复/与起点、出口、阻挡重叠，错误定位到具体索引 ----
    difficult = plan.difficult_cells
    difficult_seen: set[tuple[int, int]] = set()
    for index, cell in enumerate(difficult):
        field = f"{DIFFICULT_FIELD}.{index}"
        coord = cell.as_tuple()

        if not _in_bounds(plan, coord):
            errors.append(
                _err(
                    field,
                    f"费力通行格坐标 ({coord[0]}, {coord[1]}) 越界："
                    f"必须落在 {plan.rows} 行 × {plan.cols} 列的网格内",
                )
            )
            continue  # 越界格不再参与重合判定，避免连带噪音错误

        if coord in blocked_set:
            errors.append(
                _err(field, f"费力通行格 ({coord[0]}, {coord[1]}) 不能与阻挡格重合")
            )
        elif start_in_bounds and coord == start:
            errors.append(_err(field, "费力通行格不能标记在起点上"))
        elif target_in_bounds and coord == target:
            errors.append(_err(field, "费力通行格不能标记在出口上"))

        if coord in difficult_seen:
            errors.append(
                _err(field, f"费力通行格 ({coord[0]}, {coord[1]}) 重复出现")
            )
        difficult_seen.add(coord)

    if start == target:
        errors.append(_err("exit", "出口与起点不能是同一个格"))
    if start in blocked_set:
        errors.append(_err("start", "起点位于阻挡格上，疏散路线无法开始"))
    if target in blocked_set:
        errors.append(_err("exit", "出口位于阻挡格上，无法作为疏散终点"))

    if errors:
        raise SemanticError(errors)
