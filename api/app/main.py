"""FastAPI 入口：/api/shortest-path 与健康检查。

错误响应统一为：
    {"detail": [{"field": "<字段路径>", "message": "<可操作的中文说明>"}]}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .models import GridPlan
from .pathfinding import CELL_SIZE_METERS, find_shortest_path, path_travel_cost
from .validation import SemanticError, validate_semantics

app = FastAPI(
    title="社区礼堂轮椅疏散路线核验 API",
    version="1.1.0",
)

_FIELD_LABELS = {
    "rows": "行数",
    "cols": "列数",
    "start": "起点",
    "exit": "出口",
    "blocked": "阻挡格",
    "difficultCells": "费力通行格",
}


def _loc_to_field(loc: tuple[Any, ...]) -> str:
    """把 pydantic 的 loc（如 ('blocked', 2, 'col')）转成前端可用的字段路径。"""

    return ".".join(str(part) for part in loc)


def _explain_pydantic_error(err: dict[str, Any]) -> dict[str, str]:
    loc = err.get("loc", ())
    field = _loc_to_field(loc)
    etype = err.get("type", "")
    top = loc[0] if loc else ""
    label = _FIELD_LABELS.get(str(top), str(top) or "请求体")

    if etype in {"int_parsing", "int_type", "int_from_float"}:
        message = f"{label}必须是整数"
    elif etype == "greater_than_equal":
        limit = err.get("ctx", {}).get("ge")
        message = f"{label}不能小于 {limit}"
    elif etype == "less_than_equal":
        limit = err.get("ctx", {}).get("le")
        message = f"{label}不能大于 {limit}"
    elif etype == "missing":
        message = f"缺少必填字段“{label}”"
    elif etype == "extra_forbidden":
        message = f"存在不允许的多余字段“{field}”"
    elif etype == "list_type":
        message = f"{label}必须是坐标数组"
    elif etype == "model_type":
        message = f"{label}必须是包含 row、col 的坐标对象"
    elif etype == "too_short":
        message = f"{label}必须恰好包含 row、col 两个整数"
    else:
        message = f"{label}：{err.get('msg', '字段格式不正确')}"

    return {"field": field, "message": message}


def _validation_error_response(exc: ValidationError) -> JSONResponse:
    errors = [_explain_pydantic_error(e) for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(SemanticError)
async def semantic_error_handler(_request: Request, exc: SemanticError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors})


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/shortest-path")
async def shortest_path(request: Request) -> dict[str, Any]:
    """接受网格平面，返回唯一最短路线或不可达结论。

    请求体见 ``GridPlan``；校验失败返回 422 与字段级错误列表，
    不返回任何路线。
    """

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [{"field": "body", "message": "请求体必须是合法的 JSON 对象"}]
            },
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [{"field": "body", "message": "请求体必须是 JSON 对象"}]
            },
        )

    try:
        plan = GridPlan(**payload)
    except ValidationError as exc:
        return _validation_error_response(exc)

    # 语义校验失败时由 SemanticError 异常处理器统一返回 422
    validate_semantics(plan)

    difficult = {cell.as_tuple() for cell in (plan.difficult_cells or [])}
    path, explored_order, explored_count = find_shortest_path(plan)

    def serialize(coord: tuple[int, int]) -> dict[str, int]:
        return {"row": coord[0], "col": coord[1]}

    if path is None:
        return {
            "reachable": False,
            "message": "不可达：在当前阻挡布局下，没有任何四方向路线可以从起点到达出口",
            "path": [],
            "steps": None,
            "distanceMeters": None,
            "travelCost": None,
            "exploredCount": explored_count,
            "explored": [serialize(c) for c in explored_order],
        }

    steps = len(path) - 1  # 起点计入路线但不计步
    return {
        "reachable": True,
        "message": "找到唯一最短路线",
        "path": [serialize(c) for c in path],
        "steps": steps,
        "distanceMeters": round(steps * CELL_SIZE_METERS, 4),
        "travelCost": path_travel_cost(path, difficult),
        "exploredCount": explored_count,
        "explored": [serialize(c) for c in explored_order],
    }
