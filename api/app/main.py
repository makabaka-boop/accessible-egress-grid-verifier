"""FastAPI 入口：路线核验、通行实测与健康检查。

* ``POST /api/shortest-path``：网格平面的唯一最短路线核验；
* ``POST /api/walk-trials``、``POST /api/walk-trials/{id}/advance``、
  ``POST /api/walk-trials/{id}/undo``：
  通行实测的创建、检查点推进与撤回最后一次推进（SQLite 落库，见 ``walk.py``）；
* ``GET /api/health``：健康检查。

错误响应统一为：
    {"detail": [{"field": "<字段路径>", "message": "<可操作的中文说明>"}]}
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .models import GridPlan
from .pathfinding import CELL_SIZE_METERS, find_shortest_path, path_travel_cost
from .validation import SemanticError, validate_semantics
from .walk import (
    WalkError,
    advance_trial,
    create_trial,
    get_connection,
    parse_seconds,
    undo_trial,
    validate_create,
    validate_undo_payload,
)

app = FastAPI(
    title="社区礼堂轮椅疏散路线核验 API",
    version="1.2.0",
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


@app.exception_handler(WalkError)
async def walk_error_handler(_request: Request, exc: WalkError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors})


async def _read_json_object(request: Request, *, allow_empty: bool = False) -> Any:
    """读取请求体 JSON；解析失败或不是对象时返回 422 字段级错误响应。

    ``allow_empty=True`` 时把空请求体视为空对象（用于无参数的撤回接口）。
    返回 ``(payload, None)`` 表示成功；失败时返回 ``(None, JSONResponse)``。
    """

    try:
        payload = await request.json()
    except Exception:
        if allow_empty and not (await request.body()).strip():
            return {}, None
        return None, JSONResponse(
            status_code=422,
            content={
                "detail": [{"field": "body", "message": "请求体必须是合法的 JSON 对象"}]
            },
        )
    if not isinstance(payload, dict):
        return None, JSONResponse(
            status_code=422,
            content={
                "detail": [{"field": "body", "message": "请求体必须是 JSON 对象"}]
            },
        )
    return payload, None


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/shortest-path")
async def shortest_path(request: Request) -> Any:
    """接受网格平面，返回唯一最短路线或不可达结论。

    请求体见 ``GridPlan``；校验失败返回 422 与字段级错误列表，
    不返回任何路线。
    """

    payload, bad = await _read_json_object(request)
    if bad is not None:
        return bad

    try:
        plan = GridPlan(**payload)
    except ValidationError as exc:
        return _validation_error_response(exc)

    # 语义校验失败时由 SemanticError 异常处理器统一返回 422
    validate_semantics(plan)

    difficult = {cell.as_tuple() for cell in plan.difficult_cells}
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


# --------------------------------------------------------------------------- #
# 通行实测（只开放三个写接口：创建实测、推进检查点、撤回最后一次推进）
# --------------------------------------------------------------------------- #


@app.post("/api/walk-trials")
async def create_walk_trial(
    request: Request,
    conn=Depends(get_connection),
) -> Any:
    """以成功核验返回的不可变路线快照创建一次通行实测。

    校验：路线至少两格，且相邻坐标仅四方向移动；可选的 ``targetSeconds``
    （1–3600 的整数）随实测落库，用于把每段判定为超时/达标，类型或范围
    非法时定位到 ``targetSeconds`` 字段。失败返回 422 字段级错误，
    不落库。创建成功后检查点停在起点（第 0 格），累计时间为 0。
    """

    payload, bad = await _read_json_object(request)
    if bad is not None:
        return bad
    model = validate_create(payload)
    return create_trial(conn, model)


@app.post("/api/walk-trials/{trial_id}/advance")
async def advance_walk_trial(
    trial_id: str,
    request: Request,
    conn=Depends(get_connection),
) -> Any:
    """确认轮椅到达下一格并记录该段秒数，返回推进后的完整进度。

    秒数不是 1 至 3600 的整数、编号不存在、或实测完成后继续推进，
    均返回 422 字段级错误且数据不发生变化。
    """

    payload, bad = await _read_json_object(request)
    if bad is not None:
        return bad
    # 先校验秒数（无需查库即可拒绝），再校验编号与完成状态；
    # 任一失败都在写库之前抛出，保证数据不变。
    seconds = parse_seconds(payload)
    return advance_trial(conn, trial_id, seconds)


@app.post("/api/walk-trials/{trial_id}/undo")
async def undo_walk_trial(
    trial_id: str,
    request: Request,
    conn=Depends(get_connection),
) -> Any:
    """撤回最后一次推进：删除末段记录、回退检查点，返回完整进度。

    撤回已完成实测的末段后，记录恢复为进行中（总耗时解锁），可按正确
    秒数继续推进。尚无已确认分段（``checkpoint`` 字段）或编号不存在
    （``trialId`` 字段）时返回 422 字段级错误，且数据不发生变化。
    请求体可为空；多余字段一律拒绝。
    """

    payload, bad = await _read_json_object(request, allow_empty=True)
    if bad is not None:
        return bad
    # 先校验请求体（无需查库即可拒绝），再校验编号与是否有可撤回分段；
    # 任一失败都在写库之前抛出，保证数据不变。
    validate_undo_payload(payload)
    return undo_trial(conn, trial_id)
