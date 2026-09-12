"""通行实测后端测试：创建 / 推进两个写接口、跨请求累积与最终落库。

每个用例通过 FastAPI 的 ``dependency_overrides`` 把数据库连接指向一个
临时 SQLite 文件，因此同一个实测编号在多个 HTTP 请求之间共享状态
（贴近 API 进程内真实持久化），用例结束后删除文件。
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_connection
from app.walk import _connect, run_migrations


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "walk_test.db"

    def override_get_connection():
        # 与生产一致：autocommit + busy_timeout + 显式立即事务
        conn = _connect(str(db_path))
        run_migrations(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_connection] = override_get_connection
    with TestClient(app) as c:
        c.db_path = str(db_path)  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


def path2(*start_extra: dict) -> list[dict]:
    """3x3 核验成功的 右右下下 路线（5 格、4 段）。"""
    return [
        {"row": 0, "col": 0},
        {"row": 0, "col": 1},
        {"row": 0, "col": 2},
        {"row": 1, "col": 2},
        {"row": 2, "col": 2},
    ]


def create_trial(client, path) -> dict:
    res = client.post("/api/walk-trials", json={"path": path})
    assert res.status_code == 200, res.text
    return res.json()


def advance(client, trial_id, seconds):
    return client.post(f"/api/walk-trials/{trial_id}/advance", json={"seconds": seconds})


def open_db(client) -> sqlite3.Connection:
    conn = sqlite3.connect(client.db_path)
    conn.row_factory = sqlite3.Row
    return conn


# -------------------------------------------------------------------------- #
# 创建实测
# -------------------------------------------------------------------------- #


def test_create_trial_snapshots_path_and_checkpoint_zero(client):
    data = create_trial(client, path2())
    assert data["status"] == "in_progress"
    assert data["completed"] is False
    assert data["path"] == path2()  # 不可变快照原样回显
    assert data["totalSteps"] == 4
    assert data["checkpoint"] == 0
    assert data["elapsedSeconds"] == 0
    assert data["totalSeconds"] is None
    assert data["progressPercent"] == 0
    assert data["remainingSteps"] == 4
    assert data["segments"] == []
    # 检查点停在起点：下一坐标是第 1 格
    assert data["nextCoordinate"] == {"row": 0, "col": 1}
    assert isinstance(data["id"], str) and len(data["id"]) >= 16
    assert data["createdAt"]


def test_create_persists_trial_row(client):
    data = create_trial(client, path2())
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (data["id"],)).fetchone()
    assert row is not None
    assert json.loads(row["path_snapshot"]) == path2()
    assert row["total_steps"] == 4
    assert row["checkpoint"] == 0
    assert row["elapsed_seconds"] == 0
    assert row["total_seconds"] is None
    assert row["completed"] == 0


def test_create_two_cells_minimum(client):
    data = create_trial(client, [{"row": 1, "col": 1}, {"row": 1, "col": 2}])
    assert data["totalSteps"] == 1
    assert data["nextCoordinate"] == {"row": 1, "col": 2}


def test_create_rejects_single_cell(client):
    res = client.post("/api/walk-trials", json={"path": [{"row": 0, "col": 0}]})
    assert res.status_code == 422
    body = res.json()
    assert "id" not in body
    assert any(e["field"] == "path" and "至少需要 2 格" in e["message"] for e in body["detail"])
    with open_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM walk_trials").fetchone()[0] == 0


def test_create_rejects_empty_path(client):
    res = client.post("/api/walk-trials", json={"path": []})
    assert res.status_code == 422
    assert any(e["field"] == "path" for e in res.json()["detail"])


def test_create_rejects_missing_path(client):
    res = client.post("/api/walk-trials", json={})
    assert res.status_code == 422
    assert res.json()["detail"][0]["field"] == "path"


def test_create_rejects_diagonal_move(client):
    # (0,0) -> (1,1) 是斜向，不是四方向
    diagonal = [
        {"row": 0, "col": 0},
        {"row": 1, "col": 1},
        {"row": 2, "col": 1},
    ]
    res = client.post("/api/walk-trials", json={"path": diagonal})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "path.1" and "四方向" in e["message"] for e in detail)
    with open_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM walk_trials").fetchone()[0] == 0


def test_create_rejects_two_cell_jump(client):
    # (0,0) -> (0,2) 跳过一格
    jump = [{"row": 0, "col": 0}, {"row": 0, "col": 2}, {"row": 0, "col": 3}]
    res = client.post("/api/walk-trials", json={"path": jump})
    assert res.status_code == 422
    assert any(e["field"] == "path.1" for e in res.json()["detail"])


def test_create_rejects_self_loop(client):
    # 相邻段原地不动（曼哈顿距离 0）也不允许
    res = client.post(
        "/api/walk-trials",
        json={"path": [{"row": 0, "col": 0}, {"row": 0, "col": 0}]},
    )
    assert res.status_code == 422


def test_create_rejects_non_four_direction_even_if_later_valid(client):
    # 第一段合法，第二段非法：错误定位到 path.2
    p = [
        {"row": 0, "col": 0},
        {"row": 0, "col": 1},
        {"row": 2, "col": 1},  # 下跳两格
        {"row": 2, "col": 2},
    ]
    res = client.post("/api/walk-trials", json={"path": p})
    assert res.status_code == 422
    assert any(e["field"] == "path.2" for e in res.json()["detail"])


def test_create_rejects_integral_float_coordinate(client):
    res = client.post(
        "/api/walk-trials",
        json={"path": [{"row": 0, "col": 0}, {"row": 1.0, "col": 0}]},
    )
    assert res.status_code == 422
    assert any("path.1.row" == e["field"] for e in res.json()["detail"])


def test_create_rejects_extra_field(client):
    res = client.post(
        "/api/walk-trials",
        json={"path": path2(), "note": "x"},
    )
    assert res.status_code == 422
    assert any("多余字段" in e["message"] for e in res.json()["detail"])


def test_create_body_not_object(client):
    res = client.post("/api/walk-trials", json=[1, 2])
    assert res.status_code == 422
    assert res.json()["detail"][0]["field"] == "body"


# -------------------------------------------------------------------------- #
# 推进检查点：跨请求累积
# -------------------------------------------------------------------------- #


def test_advance_accumulates_across_requests(client):
    trial = create_trial(client, path2())
    tid = trial["id"]

    first = advance(client, tid, 12).json()
    assert first["checkpoint"] == 1
    assert first["elapsedSeconds"] == 12
    assert first["progressPercent"] == 25.0
    assert first["remainingSteps"] == 3
    assert first["nextCoordinate"] == {"row": 0, "col": 2}
    assert first["segments"] == [
        {"step": 1, "row": 0, "col": 1, "seconds": 12, "verdict": None}
    ]

    # 全新请求，状态来自落库快照
    second = advance(client, tid, 8).json()
    assert second["checkpoint"] == 2
    assert second["elapsedSeconds"] == 20
    assert second["progressPercent"] == 50.0
    assert second["nextCoordinate"] == {"row": 1, "col": 2}
    assert [s["seconds"] for s in second["segments"]] == [12, 8]

    third = advance(client, tid, 100).json()
    assert third["checkpoint"] == 3
    assert third["elapsedSeconds"] == 120
    assert third["progressPercent"] == 75.0
    assert third["nextCoordinate"] == {"row": 2, "col": 2}

    # 最后一段：到达出口，锁定总耗时
    done = advance(client, tid, 5).json()
    assert done["checkpoint"] == 4
    assert done["completed"] is True
    assert done["status"] == "completed"
    assert done["elapsedSeconds"] == 125
    assert done["totalSeconds"] == 125
    assert done["progressPercent"] == 100.0
    assert done["remainingSteps"] == 0
    assert done["nextCoordinate"] is None
    assert [s["seconds"] for s in done["segments"]] == [12, 8, 100, 5]
    assert [ (s["row"], s["col"]) for s in done["segments"]] == [
        (0, 1), (0, 2), (1, 2), (2, 2)
    ]


def test_final_state_matches_database(client):
    """跨请求累积结束后，接口返回与最终落库完全一致（pytest 关键诉求）。"""
    trial = create_trial(client, path2())
    tid = trial["id"]
    recorded = [15, 25, 7, 5]
    last = None
    for s in recorded:
        last = advance(client, tid, s).json()
    assert last["completed"] is True

    with open_db(client) as conn:
        trial_row = conn.execute(
            "SELECT * FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
        seg_rows = conn.execute(
            "SELECT step_index, row, col, seconds FROM walk_segments "
            "WHERE trial_id = ? ORDER BY step_index",
            (tid,),
        ).fetchall()

    assert trial_row["completed"] == 1
    assert trial_row["checkpoint"] == 4
    assert trial_row["elapsed_seconds"] == sum(recorded) == 52
    assert trial_row["total_seconds"] == 52  # 锁定值落库
    assert [r["seconds"] for r in seg_rows] == recorded
    # 每段坐标 = 路线的第 1..4 格
    assert [(r["row"], r["col"]) for r in seg_rows] == [
        (0, 1), (0, 2), (1, 2), (2, 2)
    ]
    # 接口累计与落库一致
    assert last["elapsedSeconds"] == trial_row["elapsed_seconds"]
    assert last["totalSeconds"] == trial_row["total_seconds"]


def test_one_step_trial_locks_immediately(client):
    """相邻起终点（2 格 1 段）：一次推进即完成并锁定。"""
    trial = create_trial(client, [{"row": 1, "col": 1}, {"row": 1, "col": 2}])
    done = advance(client, trial["id"], 300).json()
    assert done["completed"] is True
    assert done["checkpoint"] == 1
    assert done["totalSeconds"] == 300
    assert done["progressPercent"] == 100.0
    assert done["nextCoordinate"] is None


def test_each_segment_is_inserted_in_its_own_request(client):
    trial = create_trial(client, path2())
    tid = trial["id"]
    advance(client, tid, 11)
    advance(client, tid, 22)
    with open_db(client) as conn:
        segs = conn.execute(
            "SELECT step_index, seconds FROM walk_segments WHERE trial_id = ? ORDER BY step_index",
            (tid,),
        ).fetchall()
    assert [(r["step_index"], r["seconds"]) for r in segs] == [(1, 11), (2, 22)]


# -------------------------------------------------------------------------- #
# 并发：两名现场人员同时确认同一次实测
# -------------------------------------------------------------------------- #


def _parallel_advance(client, tid: str, seconds_list: list[int]) -> list:
    """用多个线程几乎同时发起推进请求，收集各自的 (status, body)。"""

    results: list = [None] * len(seconds_list)
    barrier = threading.Barrier(len(seconds_list))

    def worker(index: int, seconds: int) -> None:
        # 等所有线程就绪后同时放行，最大化“读到同一检查点”的竞争窗口
        barrier.wait()
        res = advance(client, tid, seconds)
        results[index] = (res.status_code, res.json())

    threads = [
        threading.Thread(target=worker, args=(i, s))
        for i, s in enumerate(seconds_list)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_two_simultaneous_confirms_both_succeed_no_500(client):
    """两名核验员同时确认同一次实测：两个请求都成功，各推进一格，不 500。"""
    trial = create_trial(
        client,
        [
            {"row": 0, "col": 0},
            {"row": 0, "col": 1},
            {"row": 0, "col": 2},
        ],
    )
    tid = trial["id"]

    statuses_bodies = _parallel_advance(client, tid, [10, 20])
    statuses = [s for s, _ in statuses_bodies]

    # 两个请求都必须是成功，绝不能出现 500
    assert statuses == [200, 200], statuses_bodies

    with open_db(client) as conn:
        row = conn.execute(
            "SELECT * FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
        detail = conn.execute(
            "SELECT step_index, row, col, seconds FROM walk_segments "
            "WHERE trial_id = ? ORDER BY step_index",
            (tid,),
        ).fetchall()

    # 两次确认都落库：检查点前进 2 格（到达出口），总耗时锁定为两者之和
    assert row["checkpoint"] == 2
    assert row["completed"] == 1
    assert row["elapsed_seconds"] == 30
    assert row["total_seconds"] == 30

    # 两个请求各写一段、step 唯一连续（没有唯一键冲突/丢失更新）；
    # 先拿到写锁的请求写 step1，所以秒数到段的归属取决于提交顺序，
    # 但 step1/step2 的坐标固定为路线第 1、2 格，秒数集合恒为 {10,20}。
    assert [r["step_index"] for r in detail] == [1, 2]
    assert [(r["row"], r["col"]) for r in detail] == [(0, 1), (0, 2)]
    assert sorted(r["seconds"] for r in detail) == [10, 20]


def test_two_simultaneous_confirms_on_one_step_trial(client):
    """单段路线同时收到两个确认：一个走完锁定，另一个得到 completed 422。

    两次确认都不应 500；先拿到写锁的请求把它的秒数锁定，另一个被拒不落库。
    """
    trial = create_trial(client, [{"row": 0, "col": 0}, {"row": 1, "col": 0}])
    tid = trial["id"]

    statuses_bodies = _parallel_advance(client, tid, [12, 34])
    statuses = sorted(s for s, _ in statuses_bodies)

    # 恰好一个 200、一个 422（不允许出现 500）
    assert statuses == [200, 422], statuses_bodies
    # 422 必须是字段级的 completed 错误，而不是服务器错误
    blocked = [b for s, b in statuses_bodies if s == 422][0]
    assert any(e["field"] == "completed" for e in blocked["detail"])

    with open_db(client) as conn:
        row = conn.execute(
            "SELECT * FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
        segs = conn.execute(
            "SELECT seconds FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchall()

    assert row["completed"] == 1
    assert row["checkpoint"] == 1
    # 只有先拿到锁的那次确认落库并锁定（12 或 34 取决于提交顺序）；
    # 被拒的另一个秒数绝不能写入。
    assert len(segs) == 1
    locked = segs[0]["seconds"]
    assert locked in (12, 34)
    assert row["total_seconds"] == locked
    assert row["elapsed_seconds"] == locked


def test_three_simultaneous_confirms_advance_three_steps(client):
    """三段路线同时三个确认：全部 200，检查点一次到位且无丢失更新。"""
    trial = create_trial(
        client,
        [
            {"row": 0, "col": 0},
            {"row": 0, "col": 1},
            {"row": 0, "col": 2},
            {"row": 0, "col": 3},
        ],
    )
    tid = trial["id"]

    statuses_bodies = _parallel_advance(client, tid, [5, 7, 9])
    assert [s for s, _ in statuses_bodies] == [200, 200, 200], statuses_bodies

    with open_db(client) as conn:
        row = conn.execute(
            "SELECT * FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
        segs = conn.execute(
            "SELECT step_index, seconds FROM walk_segments "
            "WHERE trial_id = ? ORDER BY step_index",
            (tid,),
        ).fetchall()

    assert row["checkpoint"] == 3
    assert row["completed"] == 1
    assert row["total_seconds"] == 21
    # 每段的 step_index 唯一且连续（没有唯一键冲突导致的丢失）
    assert [r["step_index"] for r in segs] == [1, 2, 3]
    # 三个秒数全部落库、各占一段（提交顺序不影响总和与多集合）
    assert sorted(r["seconds"] for r in segs) == [5, 7, 9]


def test_concurrent_unknown_id_and_valid_advance_do_not_cross(client):
    """并发中一个编号不存在、一个正常推进：互不影响，各自 422/200。"""
    trial = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
    )
    tid = trial["id"]
    barrier = threading.Barrier(2)
    results = {}

    def valid_worker():
        barrier.wait()
        res = advance(client, tid, 11)
        results["valid"] = (res.status_code, res.json())

    def unknown_worker():
        barrier.wait()
        res = advance(client, "f" * 32, 11)
        results["unknown"] = (res.status_code, res.json())

    t1 = threading.Thread(target=valid_worker)
    t2 = threading.Thread(target=unknown_worker)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results["valid"][0] == 200
    assert results["valid"][1]["checkpoint"] == 1
    assert results["unknown"][0] == 422
    assert any(e["field"] == "trialId" for e in results["unknown"][1]["detail"])


# -------------------------------------------------------------------------- #
# 推进错误：秒数 / 编号 / 完成后推进 —— 数据不发生变化
# -------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [0, -5, 3601, 1.5, 3.0, "60", True, None, [], {}])
def test_advance_rejects_invalid_seconds_without_change(client, bad):
    trial = create_trial(client, path2())
    tid = trial["id"]
    res = advance(client, tid, bad)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "seconds" for e in detail), detail

    # 数据不变：检查点仍为 0、无分段
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchone()[0]
    assert row["checkpoint"] == 0
    assert row["elapsed_seconds"] == 0
    assert seg_count == 0


def test_advance_missing_seconds_field(client):
    trial = create_trial(client, path2())
    res = client.post(f"/api/walk-trials/{trial['id']}/advance", json={})
    assert res.status_code == 422
    assert res.json()["detail"][0]["field"] == "seconds"


def test_advance_extra_field_rejected(client):
    trial = create_trial(client, path2())
    res = client.post(
        f"/api/walk-trials/{trial['id']}/advance",
        json={"seconds": 10, "who": "x"},
    )
    assert res.status_code == 422
    assert any(e["field"] == "who" for e in res.json()["detail"])
    with open_db(client) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (trial["id"],)
        ).fetchone()[0] == 0


def test_advance_boundary_seconds_accepted(client):
    trial = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
    )
    assert advance(client, trial["id"], 1).json()["elapsedSeconds"] == 1
    done = advance(client, trial["id"], 3600).json()
    assert done["completed"] is True
    assert done["totalSeconds"] == 3601


def test_advance_unknown_trial_id(client):
    res = advance(client, "deadbeefdeadbeefdeadbeefdeadbeef", 10)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "trialId" and "不存在" in e["message"] for e in detail)
    with open_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM walk_segments").fetchone()[0] == 0


def test_advance_after_completion_is_locked(client):
    trial = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 1, "col": 0}],
    )
    tid = trial["id"]
    done = advance(client, tid, 42)
    assert done.json()["completed"] is True

    # 完成后继续推进：字段级错误
    res = advance(client, tid, 99)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "completed" and "锁定" in e["message"] for e in detail)

    # 数据保持锁定值，不新增分段
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchone()[0]
    assert row["completed"] == 1
    assert row["checkpoint"] == 1
    assert row["elapsed_seconds"] == 42
    assert row["total_seconds"] == 42
    assert seg_count == 1


def test_invalid_seconds_after_completion_does_not_change_lock(client):
    trial = create_trial(client, [{"row": 0, "col": 0}, {"row": 1, "col": 0}])
    tid = trial["id"]
    advance(client, tid, 42)
    # 既完成、秒数又非法：仍 422，锁不变
    res = advance(client, tid, 0)
    assert res.status_code == 422
    with open_db(client) as conn:
        row = conn.execute(
            "SELECT total_seconds FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
    assert row["total_seconds"] == 42


# -------------------------------------------------------------------------- #
# 单段目标秒数：创建校验、逐段判定与跨请求同一落库目标
# -------------------------------------------------------------------------- #


def create_trial_with_target(client, path, target) -> dict:
    res = client.post("/api/walk-trials", json={"path": path, "targetSeconds": target})
    assert res.status_code == 200, res.text
    return res.json()


def test_create_with_target_persists_and_echoes(client):
    data = create_trial_with_target(client, path2(), 30)
    assert data["targetSeconds"] == 30
    assert data["checkpoint"] == 0
    assert data["segments"] == []
    # 目标已设定但尚无分段：汇总为零计数的空判定
    assert data["verdictSummary"] == {
        "onTargetCount": 0,
        "overtimeCount": 0,
        "onTargetCoordinates": [],
        "overtimeCoordinates": [],
    }
    with open_db(client) as conn:
        row = conn.execute(
            "SELECT target_seconds FROM walk_trials WHERE id = ?", (data["id"],)
        ).fetchone()
    assert row["target_seconds"] == 30


@pytest.mark.parametrize("boundary", [1, 3600])
def test_create_with_boundary_target_accepted(client, boundary):
    data = create_trial_with_target(client, path2(), boundary)
    assert data["targetSeconds"] == boundary


@pytest.mark.parametrize("bad", [0, -5, 3601, 1.5, 3.0, "60", True, None, [], {}])
def test_create_rejects_invalid_target_without_record(client, bad):
    res = client.post("/api/walk-trials", json={"path": path2(), "targetSeconds": bad})
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "targetSeconds" for e in detail), detail
    assert "id" not in res.json()
    # 不产生任何实测记录
    with open_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM walk_trials").fetchone()[0] == 0


def test_create_without_target_keeps_legacy_shape(client):
    """旧客户端省略目标值：无分段判定与汇总，契约与旧版一致。"""
    trial = create_trial(client, path2())
    assert trial["targetSeconds"] is None
    assert trial["verdictSummary"] is None

    done = trial
    for s in (12, 8, 100, 5):
        done = advance(client, trial["id"], s).json()
    assert done["completed"] is True
    assert done["targetSeconds"] is None
    assert done["verdictSummary"] is None
    assert all(seg["verdict"] is None for seg in done["segments"])
    with open_db(client) as conn:
        row = conn.execute(
            "SELECT target_seconds FROM walk_trials WHERE id = ?", (trial["id"],)
        ).fetchone()
    assert row["target_seconds"] is None


def test_verdicts_come_from_same_persisted_target_across_requests(client):
    """跨请求判定来自同一落库目标：推进请求不携带目标，判定仍一致。"""
    trial = create_trial_with_target(client, path2(), 30)
    tid = trial["id"]

    # 第 1 段 10 秒（≤30 达标）、第 2 段 45 秒（>30 超时）——各自独立请求
    first = advance(client, tid, 10).json()
    assert first["targetSeconds"] == 30
    assert [s["verdict"] for s in first["segments"]] == ["on_target"]
    assert first["verdictSummary"]["onTargetCount"] == 1
    assert first["verdictSummary"]["overtimeCount"] == 0
    assert first["verdictSummary"]["onTargetCoordinates"] == [{"row": 0, "col": 1}]

    second = advance(client, tid, 45).json()
    assert [s["verdict"] for s in second["segments"]] == ["on_target", "overtime"]
    assert second["verdictSummary"] == {
        "onTargetCount": 1,
        "overtimeCount": 1,
        "onTargetCoordinates": [{"row": 0, "col": 1}],
        "overtimeCoordinates": [{"row": 0, "col": 2}],
    }

    # 边界：恰好等于目标为达标；超出 1 秒即超时
    third = advance(client, tid, 30).json()
    assert third["segments"][2]["verdict"] == "on_target"
    done = advance(client, tid, 31).json()
    assert done["completed"] is True
    assert [s["verdict"] for s in done["segments"]] == [
        "on_target", "overtime", "on_target", "overtime",
    ]
    assert done["verdictSummary"]["onTargetCount"] == 2
    assert done["verdictSummary"]["overtimeCount"] == 2
    assert done["verdictSummary"]["overtimeCoordinates"] == [
        {"row": 0, "col": 2},
        {"row": 2, "col": 2},
    ]

    # 判定依据是落库目标本身（而非请求参数）：库中目标未变，响应与之同源
    with open_db(client) as conn:
        row = conn.execute(
            "SELECT target_seconds FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
        segs = conn.execute(
            "SELECT seconds FROM walk_segments WHERE trial_id = ? ORDER BY step_index",
            (tid,),
        ).fetchall()
    assert row["target_seconds"] == 30
    expected = ["overtime" if s["seconds"] > 30 else "on_target" for s in segs]
    assert [s["verdict"] for s in done["segments"]] == expected


def test_target_is_immutable_after_creation(client):
    """推进接口不接受目标字段（多余字段），落库目标永不被改写。"""
    trial = create_trial_with_target(client, path2(), 20)
    tid = trial["id"]
    res = client.post(
        f"/api/walk-trials/{tid}/advance",
        json={"seconds": 10, "targetSeconds": 99},
    )
    assert res.status_code == 422
    assert any(e["field"] == "targetSeconds" for e in res.json()["detail"])
    with open_db(client) as conn:
        row = conn.execute(
            "SELECT target_seconds, checkpoint FROM walk_trials WHERE id = ?", (tid,)
        ).fetchone()
    assert row["target_seconds"] == 20
    assert row["checkpoint"] == 0


# -------------------------------------------------------------------------- #
# 撤回最后一次推进：中途撤回重录 / 完成后撤回再完成 / 空记录拒绝
# -------------------------------------------------------------------------- #


def undo(client, trial_id):
    return client.post(f"/api/walk-trials/{trial_id}/undo", json={})


def test_undo_mid_trial_then_rerecord(client):
    """中途撤回：删除末段、回退检查点，可按正确秒数继续推进直至完成。"""
    trial = create_trial(client, path2())
    tid = trial["id"]
    for s in (12, 8, 100):
        advance(client, tid, s)

    undone = undo(client, tid)
    assert undone.status_code == 200, undone.text
    data = undone.json()
    # 返回与创建/推进相同的完整进度结构
    assert set(data.keys()) == set(trial.keys())
    assert data["checkpoint"] == 2
    assert data["elapsedSeconds"] == 20  # 12 + 8，从剩余分段重新求和
    assert data["completed"] is False
    assert data["status"] == "in_progress"
    assert data["totalSeconds"] is None
    assert data["nextCoordinate"] == {"row": 1, "col": 2}
    assert data["progressPercent"] == 50.0
    assert data["remainingSteps"] == 2
    assert [s["seconds"] for s in data["segments"]] == [12, 8]
    assert data["path"] == path2()  # 快照不变

    # 落库与响应一致：末段已删除、检查点回退
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
        segs = conn.execute(
            "SELECT step_index, seconds FROM walk_segments "
            "WHERE trial_id = ? ORDER BY step_index",
            (tid,),
        ).fetchall()
    assert row["checkpoint"] == 2
    assert row["elapsed_seconds"] == 20
    assert row["total_seconds"] is None
    assert row["completed"] == 0
    assert [(r["step_index"], r["seconds"]) for r in segs] == [(1, 12), (2, 8)]

    # 按正确秒数重录该段，再继续走到出口
    third = advance(client, tid, 40).json()
    assert third["checkpoint"] == 3
    assert third["elapsedSeconds"] == 60
    assert [s["seconds"] for s in third["segments"]] == [12, 8, 40]
    done = advance(client, tid, 5).json()
    assert done["completed"] is True
    assert done["totalSeconds"] == 65


def test_undo_completed_trial_reopens_and_can_complete_again(client):
    """完成后撤回末段：记录恢复进行中、总耗时解锁，可重新完成并锁定新值。"""
    trial = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
    )
    tid = trial["id"]
    advance(client, tid, 10)
    done = advance(client, tid, 20).json()
    assert done["completed"] is True
    assert done["totalSeconds"] == 30

    reopened = undo(client, tid).json()
    assert reopened["completed"] is False
    assert reopened["status"] == "in_progress"
    assert reopened["checkpoint"] == 1
    assert reopened["elapsedSeconds"] == 10
    assert reopened["totalSeconds"] is None  # 锁定解除
    assert reopened["nextCoordinate"] == {"row": 0, "col": 2}
    assert reopened["remainingSteps"] == 1
    assert [s["seconds"] for s in reopened["segments"]] == [10]

    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
    assert row["completed"] == 0
    assert row["total_seconds"] is None
    assert row["checkpoint"] == 1

    # 重新完成：新的末段秒数锁定为新的总耗时
    redone = advance(client, tid, 25).json()
    assert redone["completed"] is True
    assert redone["totalSeconds"] == 35
    assert [s["seconds"] for s in redone["segments"]] == [10, 25]
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
    assert row["completed"] == 1
    assert row["total_seconds"] == 35


def test_undo_all_the_way_back_to_start(client):
    """连续撤回至起点：检查点归零、累计清零，下一格回到路线第 1 格。"""
    trial = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
    )
    tid = trial["id"]
    advance(client, tid, 10)
    advance(client, tid, 20)

    first = undo(client, tid).json()
    assert first["checkpoint"] == 1
    second = undo(client, tid).json()
    assert second["checkpoint"] == 0
    assert second["elapsedSeconds"] == 0
    assert second["segments"] == []
    assert second["nextCoordinate"] == {"row": 0, "col": 1}
    assert second["progressPercent"] == 0
    assert second["remainingSteps"] == 2

    with open_db(client) as conn:
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchone()[0]
    assert seg_count == 0


def test_undo_without_confirmed_segments_rejected_no_change(client):
    """空记录（尚无已确认段）撤回：422 定位 checkpoint，数据不变。"""
    trial = create_trial(client, path2())
    tid = trial["id"]

    res = undo(client, tid)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "checkpoint" for e in detail), detail

    # 数据不变：检查点仍为 0、无分段、实测记录仍在
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchone()[0]
    assert row["checkpoint"] == 0
    assert row["elapsed_seconds"] == 0
    assert row["completed"] == 0
    assert seg_count == 0

    # 推进一段再撤回归零后，再次撤回仍被拒且不改库
    advance(client, tid, 9)
    assert undo(client, tid).status_code == 200
    res = undo(client, tid)
    assert res.status_code == 422
    assert any(e["field"] == "checkpoint" for e in res.json()["detail"])
    with open_db(client) as conn:
        row = conn.execute("SELECT checkpoint FROM walk_trials WHERE id = ?", (tid,)).fetchone()
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchone()[0]
    assert row["checkpoint"] == 0
    assert seg_count == 0


def test_undo_unknown_trial_id(client):
    res = undo(client, "deadbeefdeadbeefdeadbeefdeadbeef")
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "trialId" and "不存在" in e["message"] for e in detail)
    with open_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM walk_segments").fetchone()[0] == 0


def test_undo_with_target_recomputes_verdict_summary(client):
    """设有目标时撤回：分类汇总从剩余分段重新生成，坐标与计数准确。"""
    trial = create_trial_with_target(client, path2(), 15)
    tid = trial["id"]
    # 10 达标、20 超时、30 超时、5 达标 → 完成后 达标2 / 超时2
    for s in (10, 20, 30, 5):
        last = advance(client, tid, s).json()
    assert last["completed"] is True
    assert last["verdictSummary"]["onTargetCount"] == 2
    assert last["verdictSummary"]["overtimeCount"] == 2

    # 撤回末段（5 秒达标段）：恢复进行中，汇总只剩 达标1 / 超时2
    undone = undo(client, tid).json()
    assert undone["completed"] is False
    assert undone["targetSeconds"] == 15
    assert [s["verdict"] for s in undone["segments"]] == [
        "on_target", "overtime", "overtime",
    ]
    assert undone["verdictSummary"] == {
        "onTargetCount": 1,
        "overtimeCount": 2,
        "onTargetCoordinates": [{"row": 0, "col": 1}],
        "overtimeCoordinates": [{"row": 0, "col": 2}, {"row": 1, "col": 2}],
    }
    assert undone["nextCoordinate"] == {"row": 2, "col": 2}

    # 再撤回一段（30 秒超时段）：汇总只剩 达标1 / 超时1
    undone2 = undo(client, tid).json()
    assert undone2["verdictSummary"] == {
        "onTargetCount": 1,
        "overtimeCount": 1,
        "onTargetCoordinates": [{"row": 0, "col": 1}],
        "overtimeCoordinates": [{"row": 0, "col": 2}],
    }

    # 重录末段为达标秒数并再次完成：汇总随之更新
    advance(client, tid, 12)
    redone = advance(client, tid, 40).json()
    assert redone["completed"] is True
    assert redone["verdictSummary"] == {
        "onTargetCount": 2,
        "overtimeCount": 2,
        "onTargetCoordinates": [{"row": 0, "col": 1}, {"row": 1, "col": 2}],
        "overtimeCoordinates": [{"row": 0, "col": 2}, {"row": 2, "col": 2}],
    }
    assert redone["totalSeconds"] == 10 + 20 + 12 + 40


def test_undo_without_target_keeps_legacy_shape(client):
    """未设目标的实测撤回后仍无判定与汇总（与旧契约一致）。"""
    trial = create_trial(client, path2())
    tid = trial["id"]
    advance(client, tid, 10)
    advance(client, tid, 20)
    undone = undo(client, tid).json()
    assert undone["targetSeconds"] is None
    assert undone["verdictSummary"] is None
    assert all(s["verdict"] is None for s in undone["segments"])


def test_undo_rejects_extra_body_field(client):
    trial = create_trial(client, path2())
    advance(client, trial["id"], 10)
    res = client.post(f"/api/walk-trials/{trial['id']}/undo", json={"seconds": 5})
    assert res.status_code == 422
    assert any(e["field"] == "seconds" for e in res.json()["detail"])
    # 数据不变：分段仍在
    with open_db(client) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (trial["id"],)
        ).fetchone()[0] == 1


def test_undo_accepts_empty_body(client):
    """撤回接口允许完全不带请求体（空体视为空对象）。"""
    trial = create_trial(client, path2())
    advance(client, trial["id"], 10)
    res = client.post(f"/api/walk-trials/{trial['id']}/undo")
    assert res.status_code == 200
    assert res.json()["checkpoint"] == 0


def test_two_simultaneous_undos_both_succeed_no_500(client):
    """两名核验员同时撤回：请求串行化，各撤一段，不 500、不丢更新。"""
    trial = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
    )
    tid = trial["id"]
    advance(client, tid, 10)
    advance(client, tid, 20)

    results: list = [None, None]
    barrier = threading.Barrier(2)

    def worker(index: int) -> None:
        barrier.wait()
        res = undo(client, tid)
        results[index] = (res.status_code, res.json())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 两次撤回都成功：各删一段，最终回到起点
    assert [s for s, _ in results] == [200, 200], results
    checkpoints = sorted(b["checkpoint"] for _, b in results)
    assert checkpoints == [0, 1]
    with open_db(client) as conn:
        row = conn.execute("SELECT * FROM walk_trials WHERE id = ?", (tid,)).fetchone()
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM walk_segments WHERE trial_id = ?", (tid,)
        ).fetchone()[0]
    assert row["checkpoint"] == 0
    assert row["elapsed_seconds"] == 0
    assert seg_count == 0


# -------------------------------------------------------------------------- #
# 迁移与表结构
# -------------------------------------------------------------------------- #


def test_migrations_are_idempotent(tmp_path):
    db_path = tmp_path / "m.db"
    conn = sqlite3.connect(db_path)
    run_migrations(conn)
    run_migrations(conn)  # 再跑一次不报错、不重建
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 1
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"walk_trials", "walk_segments"} <= tables
    conn.close()


def test_migration_v2_adds_target_seconds_to_legacy_db(tmp_path):
    """v1 旧库升级到 v2：新增 target_seconds 列，历史实测目标为 NULL。"""
    from app.walk import _MIGRATIONS

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # 模拟只执行过 v1 的旧库：两张表 + 一条历史实测（无目标列）
    for _, statements in _MIGRATIONS:
        if _ == 1:
            for statement in statements:
                conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")
    conn.execute(
        """
        INSERT INTO walk_trials
            (id, created_at, path_snapshot, total_steps, checkpoint,
             elapsed_seconds, total_seconds, completed)
        VALUES ('legacy1', '2026-01-01T00:00:00+00:00', '[{"row":0,"col":0},{"row":0,"col":1}]',
                1, 0, 0, NULL, 0)
        """
    )
    conn.commit()

    run_migrations(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version >= 2
    columns = {
        r[1] for r in conn.execute("PRAGMA table_info(walk_trials)").fetchall()
    }
    assert "target_seconds" in columns
    row = conn.execute("SELECT target_seconds FROM walk_trials WHERE id = 'legacy1'").fetchone()
    assert row["target_seconds"] is None  # 历史实测不判定
    conn.close()


def test_two_trials_are_isolated(client):
    a = create_trial(client, path2())
    b = create_trial(
        client,
        [{"row": 0, "col": 0}, {"row": 1, "col": 0}, {"row": 2, "col": 0}],
    )
    advance(client, a["id"], 5)
    advance(client, b["id"], 7)
    advance(client, b["id"], 3)

    with open_db(client) as conn:
        rows = {
            r["id"]: r
            for r in conn.execute("SELECT * FROM walk_trials").fetchall()
        }
    assert rows[a["id"]]["checkpoint"] == 1
    assert rows[a["id"]]["elapsed_seconds"] == 5
    assert rows[b["id"]]["checkpoint"] == 2
    assert rows[b["id"]]["elapsed_seconds"] == 10
    assert rows[a["id"]]["total_seconds"] is None
