"""通行实测后端测试：创建 / 推进两个写接口、跨请求累积与最终落库。

每个用例通过 FastAPI 的 ``dependency_overrides`` 把数据库连接指向一个
临时 SQLite 文件，因此同一个实测编号在多个 HTTP 请求之间共享状态
（贴近 API 进程内真实持久化），用例结束后删除文件。
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_connection
from app.walk import run_migrations


@pytest.fixture()
def client(tmp_path):
    db_path = tmp_path / "walk_test.db"

    def override_get_connection():
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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
    assert first["segments"] == [{"step": 1, "row": 0, "col": 1, "seconds": 12}]

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
