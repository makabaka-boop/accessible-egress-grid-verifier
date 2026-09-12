"""通行实测：SQLite 落库、建表迁移与读写服务（全部在 API 进程内完成）。

核心数据是一次实测的 **不可变路线快照** 与 **当前检查点**：

* ``walk_trials`` 保存实测编号、创建时间、快照（JSON）、总步数、
  当前检查点序号、累计/总耗时、完成状态与可选的单段目标秒数；
  创建后路线与目标永不再变。
* ``walk_segments`` 逐段保存“从上一检查点进入本格”的实测秒数，
  推进检查点只做 INSERT，累计时间由这些落库的分段求和得到；
  设定了目标的实测在读取进度时按“本段秒数 > 目标 → 超时，否则达标”
  逐段判定，判定结果与落库目标天然一致，无需额外落库。

对外只暴露两个写操作（见 ``main`` 中的路由）：
``create_trial`` 与 ``advance_trial``；不提供任何修改/删除接口。

错误统一抛 :class:`WalkError`，携带与既有接口相同的字段级错误
结构 ``[{"field": ..., "message": ...}, ...]``，由主应用转成 422。
任何校验失败都在写库之前返回，数据不发生变化。
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from .walk_models import MAX_SECONDS, MIN_SECONDS, WalkTrialCreate

# 进程内 SQLite：默认落在 api/var/walk_trials.db，可用环境变量覆盖。
DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "var")
DEFAULT_DB_PATH = os.environ.get(
    "WALK_DB_PATH", os.path.join(DEFAULT_DB_DIR, "walk_trials.db")
)

# 建表迁移：以 PRAGMA user_version 为版本号，顺序执行、只执行一次。
# 新增表结构时在末尾追加 (version, sql_list) 即可。
_MIGRATIONS: list[tuple[int, tuple[str, ...]]] = [
    (
        1,
        (
            """
            CREATE TABLE IF NOT EXISTS walk_trials (
                id              TEXT PRIMARY KEY,
                created_at      TEXT NOT NULL,
                path_snapshot   TEXT NOT NULL,
                total_steps     INTEGER NOT NULL,
                checkpoint      INTEGER NOT NULL DEFAULT 0,
                elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                total_seconds   INTEGER,
                completed       INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS walk_segments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trial_id    TEXT NOT NULL,
                step_index  INTEGER NOT NULL,
                row         INTEGER NOT NULL,
                col         INTEGER NOT NULL,
                seconds     INTEGER NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE (trial_id, step_index),
                FOREIGN KEY (trial_id) REFERENCES walk_trials (id)
            )
            """,
        ),
    ),
    (
        2,
        (
            # 可选单段目标秒数固化到实测记录：NULL 表示该实测不做超时/达标
            # 判定（旧客户端与历史数据的默认形态）。
            """
            ALTER TABLE walk_trials ADD COLUMN target_seconds INTEGER
            """,
        ),
    ),
]


class WalkError(Exception):
    """携带字段级错误信息的实测请求失败（对应 HTTP 422）。"""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__(f"{len(errors)} walk error(s)")


def _err(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


# --------------------------------------------------------------------------- #
# 数据库连接与迁移
# --------------------------------------------------------------------------- #


def _connect(db_path: str) -> sqlite3.Connection:
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    # FastAPI 的同步依赖在线程池中执行、TestClient 又跨 anyio 门户线程，
    # 每次请求各自一条连接；关闭同线程限制即可安全使用。
    # isolation_level=None（autocommit）：事务由 _immediate_txn 显式控制，
    # 避免隐式事务在并发写时产生意外的“先读后锁”窗口。
    conn = sqlite3.connect(
        db_path, timeout=10, check_same_thread=False, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 并发写时第二个事务等待写锁，最长等 10 秒后才报 SQLITE_BUSY。
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextlib.contextmanager
def _immediate_txn(conn: sqlite3.Connection):
    """``BEGIN IMMEDIATE`` 立即取写锁的事务：把同一次实测的推进串行化。

    两名现场人员同时确认同一次实测时，两个请求各自持有连接：先进入的
    事务拿到写锁，后到的事务在忙等待后才开始，因此锁内能读到上一个请求
    已提交的最新检查点，两次确认依次落库——既不会 500，也不会只前进一格。
    任意业务错误（:class:`WalkError`）都回滚，不写入任何分段。
    """

    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def run_migrations(conn: sqlite3.Connection) -> None:
    """按 ``PRAGMA user_version`` 顺序执行建表迁移（幂等）。"""

    # 迁移本身幂等且通常只在首次执行，用一个立即事务包住避免并发首启竞争。
    with _immediate_txn(conn):
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, statements in _MIGRATIONS:
            if version <= current:
                continue
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")


def get_connection():
    """FastAPI 依赖：每请求打开一条已迁移的连接，请求结束后关闭。"""

    conn = _connect(DEFAULT_DB_PATH)
    run_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 请求校验
# --------------------------------------------------------------------------- #


def validate_create(payload: Any) -> WalkTrialCreate:
    """校验创建实测请求体。

    结构（类型/多余字段/坐标非负整数）交给 Pydantic；
    这里额外要求路线至少两格、相邻坐标仅四方向移动，
    并校验可选的单段目标秒数（1–3600 的整数，省略则不判定）。
    """

    if not isinstance(payload, dict):
        raise WalkError([_err("body", "请求体必须是 JSON 对象")])

    if "path" not in payload:
        raise WalkError([_err("path", "缺少路线快照：请从一次成功的路线核验发起实测")])

    raw_path = payload["path"]
    if not isinstance(raw_path, list):
        raise WalkError([_err("path", "路线快照必须是坐标数组")])
    if len(raw_path) < 2:
        raise WalkError(
            [_err("path", f"路线至少需要 2 格（起点与出口），当前只有 {len(raw_path)} 格")]
        )

    # 可选目标秒数：类型/范围非法时定位到 targetSeconds，不产生实测记录
    parse_target_seconds(payload)

    # 结构/类型校验（坐标为严格非负整数、拒绝多余字段）
    try:
        model = WalkTrialCreate.model_validate(payload)
    except Exception as exc:  # pragma: no cover - 经由 parse_create 统一处理
        raise WalkError(_format_model_errors(exc)) from exc

    # 相邻坐标只允许四方向移动（曼哈顿距离恰好为 1，不允许斜向/跳跃/原地）
    coords = [(cell.row, cell.col) for cell in model.path]
    for index in range(1, len(coords)):
        prev = coords[index - 1]
        cur = coords[index]
        if abs(cur[0] - prev[0]) + abs(cur[1] - prev[1]) != 1:
            raise WalkError(
                [
                    _err(
                        f"path.{index}",
                        f"第 {index} 段路线必须四方向移动（上/下/左/右各一格）："
                        f"({prev[0]}, {prev[1]}) → ({cur[0]}, {cur[1]}) 不是相邻格",
                    )
                ]
            )

    return model


def _format_model_errors(exc: Exception) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for raw in getattr(exc, "errors", lambda: [])():
        loc = raw.get("loc", ())
        field = ".".join(str(part) for part in loc) or "path"
        etype = raw.get("type", "")
        top = loc[0] if loc else "path"
        label = "路线快照" if top == "path" else field
        if etype in {"int_parsing", "int_type", "int_from_float"}:
            message = f"{label}中的坐标必须是整数"
        elif etype == "greater_than_equal":
            message = f"{label}中的坐标不能小于 0"
        elif etype == "model_type":
            message = f"{label}必须是包含 row、col 的坐标对象"
        elif etype == "list_type":
            message = "路线快照必须是坐标数组"
        elif etype == "extra_forbidden":
            message = f"存在不允许的多余字段“{field}”"
        else:
            message = f"{label}：{raw.get('msg', '字段格式不正确')}"
        errors.append(_err(field, message))
    return errors or [_err("path", "路线快照格式不正确")]


def parse_seconds(payload: Any) -> int:
    """校验推进实测请求体中的秒数：必须是 1 至 3600 的整数。

    整值小数（3.0）、布尔、字符串、越界整数一律拒绝，且在访问数据库前
    失败，保证数据不发生变化。
    """

    if not isinstance(payload, dict):
        raise WalkError([_err("body", "请求体必须是 JSON 对象")])
    if "seconds" not in payload:
        raise WalkError([_err("seconds", "缺少必填字段“秒数”")])

    extra = sorted(key for key in payload if key != "seconds")
    if extra:
        raise WalkError(
            [_err(extra[0], f"存在不允许的多余字段“{extra[0]}”")]
        )

    value = payload["seconds"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise WalkError([_err("seconds", f"秒数必须是 {MIN_SECONDS} 至 {MAX_SECONDS} 之间的整数")])
    if not (MIN_SECONDS <= value <= MAX_SECONDS):
        raise WalkError(
            [_err("seconds", f"秒数必须在 {MIN_SECONDS} 至 {MAX_SECONDS} 之间，当前为 {value}")]
        )
    return value


def parse_target_seconds(payload: dict[str, Any]) -> int | None:
    """校验创建请求中可选的单段目标秒数。

    省略字段 → 返回 ``None``（不判定，与旧客户端契约一致）；提供时必须是
    1 至 3600 的整数，整值小数（3.0）、布尔、字符串、显式 null、越界整数
    一律以 ``targetSeconds`` 字段错误拒绝，且在写库之前失败，
    不产生任何实测记录。
    """

    if "targetSeconds" not in payload:
        return None
    value = payload["targetSeconds"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise WalkError(
            [_err("targetSeconds", f"目标秒数必须是 {MIN_SECONDS} 至 {MAX_SECONDS} 之间的整数")]
        )
    if not (MIN_SECONDS <= value <= MAX_SECONDS):
        raise WalkError(
            [_err("targetSeconds", f"目标秒数必须在 {MIN_SECONDS} 至 {MAX_SECONDS} 之间，当前为 {value}")]
        )
    return value


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #


def _serialize_progress(
    trial_row: sqlite3.Row,
    path: list[dict[str, int]],
    segments: list[sqlite3.Row],
) -> dict[str, Any]:
    """构造推进/创建接口共用的完整进度响应。

    设定了单段目标的实测：每段按“秒数 > 目标 → 超时（overtime），否则
    达标（on_target）”判定，并给出分类汇总（两类各自的段数与坐标）；
    未设定目标（旧客户端/历史数据）时 ``verdict`` 与汇总均为 ``null``，
    响应形态与旧契约一致。
    """

    checkpoint = trial_row["checkpoint"]
    total_steps = trial_row["total_steps"]
    completed = bool(trial_row["completed"])
    target = trial_row["target_seconds"]

    segment_list = []
    for seg in segments:
        verdict = None
        if target is not None:
            verdict = "overtime" if seg["seconds"] > target else "on_target"
        segment_list.append(
            {
                "step": seg["step_index"],
                "row": seg["row"],
                "col": seg["col"],
                "seconds": seg["seconds"],
                "verdict": verdict,
            }
        )

    verdict_summary = None
    if target is not None:
        on_target_coords = [
            {"row": s["row"], "col": s["col"]}
            for s in segment_list
            if s["verdict"] == "on_target"
        ]
        overtime_coords = [
            {"row": s["row"], "col": s["col"]}
            for s in segment_list
            if s["verdict"] == "overtime"
        ]
        verdict_summary = {
            "onTargetCount": len(on_target_coords),
            "overtimeCount": len(overtime_coords),
            "onTargetCoordinates": on_target_coords,
            "overtimeCoordinates": overtime_coords,
        }

    if not completed:
        # 已确认 checkpoint 段（当前位于 path[checkpoint]），下一格是 path[checkpoint+1]
        next_cell = path[checkpoint + 1]
        next_coordinate = {"row": next_cell["row"], "col": next_cell["col"]}
        remaining = total_steps - checkpoint
    else:
        next_coordinate = None
        remaining = 0

    return {
        "id": trial_row["id"],
        "status": "completed" if completed else "in_progress",
        "path": path,  # 不可变路线快照，原样回显
        "totalSteps": total_steps,
        "checkpoint": checkpoint,  # 已确认到达的格序号（0 = 仍在起点）
        "nextCoordinate": next_coordinate,
        "elapsedSeconds": trial_row["elapsed_seconds"],
        "totalSeconds": trial_row["total_seconds"],
        "targetSeconds": target,  # 落库的可选单段目标；未设定为 null
        "verdictSummary": verdict_summary,  # 超时/达标分类汇总；未设定目标为 null
        "progressPercent": round(checkpoint * 100 / total_steps, 2),
        "remainingSteps": remaining,
        "completed": completed,
        "segments": segment_list,
        "createdAt": trial_row["created_at"],
    }


def _load_progress(conn: sqlite3.Connection, trial_id: str) -> dict[str, Any] | None:
    trial = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (trial_id,)).fetchone()
    if trial is None:
        return None
    path = json.loads(trial["path_snapshot"])
    segments = conn.execute(
        "SELECT * FROM walk_segments WHERE trial_id = ? ORDER BY step_index",
        (trial_id,),
    ).fetchall()
    return _serialize_progress(trial, path, segments)


# --------------------------------------------------------------------------- #
# 两个写操作
# --------------------------------------------------------------------------- #


def create_trial(conn: sqlite3.Connection, model: WalkTrialCreate) -> dict[str, Any]:
    """以不可变路线快照创建一次实测，检查点停在起点（第 0 格）。

    可选的单段目标秒数随实测记录一并落库，之后每次推进的判定都
    以这个落库值为准（跨请求一致）。
    """

    path = [{"row": cell.row, "col": cell.col} for cell in model.path]
    trial_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    total_steps = len(path) - 1

    with _immediate_txn(conn):
        conn.execute(
            """
            INSERT INTO walk_trials
                (id, created_at, path_snapshot, total_steps, checkpoint,
                 elapsed_seconds, total_seconds, completed, target_seconds)
            VALUES (?, ?, ?, ?, 0, 0, NULL, 0, ?)
            """,
            (trial_id, now, json.dumps(path, ensure_ascii=False), total_steps,
             model.target_seconds),
        )
    progress = _load_progress(conn, trial_id)
    assert progress is not None
    return progress


def advance_trial(conn: sqlite3.Connection, trial_id: str, seconds: int) -> dict[str, Any]:
    """确认到达下一格：记录该段秒数、推进检查点。

    * 编号不存在 → 422（trialId 字段），不写任何数据；
    * 已完成仍推进 → 422（completed 字段），不写任何数据；
    * 成功 → 返回推进后的完整进度；最后一段确认后锁定总耗时。

    整个“读当前检查点 → 插分段 → 推进”过程放在 ``BEGIN IMMEDIATE`` 写
    事务内，锁内读到的一定是已提交的最新检查点。两名核验员同时确认同一
    次实测时，两个请求串行提交：第一次写 step k+1，第二次在锁释放后读到
    新检查点并写 step k+2，各前进一格、互不覆盖，也不会因
    ``UNIQUE(trial_id, step_index)`` 冲突而 500。
    """

    with _immediate_txn(conn):
        # 锁内重读：拿到的一定是此前已提交事务推进后的最新状态
        trial = conn.execute(
            "SELECT * FROM walk_trials WHERE id = ?", (trial_id,)
        ).fetchone()
        if trial is None:
            raise WalkError([_err("trialId", f"实测编号不存在：{trial_id}")])
        if trial["completed"]:
            raise WalkError(
                [_err("completed", "该实测已到达出口并锁定总耗时，不能继续推进；如需重测请发起新实测")]
            )

        checkpoint = trial["checkpoint"]
        total_steps = trial["total_steps"]
        path = json.loads(trial["path_snapshot"])
        # 当前位于 path[checkpoint]，本次确认到达下一格 path[checkpoint + 1]
        next_index = checkpoint + 1
        target = path[next_index]
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO walk_segments
                (trial_id, step_index, row, col, seconds, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (trial_id, next_index, target["row"], target["col"], seconds, now),
        )

        new_elapsed = trial["elapsed_seconds"] + seconds
        completed = next_index >= total_steps
        conn.execute(
            """
            UPDATE walk_trials
               SET checkpoint = ?,
                   elapsed_seconds = ?,
                   total_seconds = CASE WHEN ? = 1 THEN ? ELSE total_seconds END,
                   completed = ?
             WHERE id = ?
            """,
            (next_index, new_elapsed, 1 if completed else 0, new_elapsed,
             1 if completed else 0, trial_id),
        )

    progress = _load_progress(conn, trial_id)
    assert progress is not None
    return progress
