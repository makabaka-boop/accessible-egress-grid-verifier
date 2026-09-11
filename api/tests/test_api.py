"""端到端级别的 API 测试（FastAPI TestClient）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post_plan(plan: dict):
    return client.post("/api/shortest-path", json=plan)


def base_plan(**overrides) -> dict:
    plan = {
        "rows": 3,
        "cols": 3,
        "start": {"row": 0, "col": 0},
        "exit": {"row": 2, "col": 2},
        "blocked": [],
    }
    plan.update(overrides)
    return plan


# ---------- 正常路径 ----------

def test_open_grid_shortest_path():
    res = post_plan(base_plan())
    assert res.status_code == 200
    data = res.json()
    assert data["reachable"] is True
    # 最近路线 4 步：右上/下的等长组合中按 上右下左 唯一确定为
    # (0,0) -> 下移不被阻挡，但第一选择是右……此处验证长度与步数即可
    assert data["steps"] == 4
    assert len(data["path"]) == 5
    assert data["path"][0] == {"row": 0, "col": 0}
    assert data["path"][-1] == {"row": 2, "col": 2}
    assert data["distanceMeters"] == 2.0
    assert data["exploredCount"] == len(data["explored"])
    assert data["exploredCount"] >= 1


def test_direction_tie_break_is_up_right_down_left():
    """3x3 空网格，(0,0)->(2,2)：先到达出口的路线必须是“先右两格再下两格”。

    BFS 从 (0,0) 扩展：上越界，右=(0,1) 入队，下=(1,0) 入队。
    距离 2 层顺序为 (0,2)、(1,1)[来自(0,1)下]、(1,1)[来自(1,0)右 已访问]、(2,0)。
    出口 (2,2) 经由 (1,2)->下 与 (2,1)->右 到达，
    (1,2) 更早入队，故唯一路线为 右右下下。
    """
    res = post_plan(base_plan())
    assert res.status_code == 200
    path = [(c["row"], c["col"]) for c in res.json()["path"]]
    assert path == [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)]


def test_vertical_movement_when_up_priority_applies():
    """2x2 空网格 (1,0)->(0,1)：上(0,0) 先于 右(1,1)，路线为 上、右。"""
    plan = base_plan(rows=2, cols=2, start={"row": 1, "col": 0}, exit={"row": 0, "col": 1})
    res = post_plan(plan)
    assert res.status_code == 200
    path = [(c["row"], c["col"]) for c in res.json()["path"]]
    assert path == [(1, 0), (0, 0), (0, 1)]
    assert res.json()["steps"] == 2
    assert res.json()["distanceMeters"] == 1.0


def test_blocked_cells_force_detour():
    plan = base_plan(blocked=[{"row": 0, "col": 1}, {"row": 1, "col": 1}])
    res = post_plan(plan)
    assert res.status_code == 200
    data = res.json()
    assert data["reachable"] is True
    path = [(c["row"], c["col"]) for c in data["path"]]
    assert path == [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)]
    assert data["steps"] == 4
    assert data["distanceMeters"] == 2.0


def test_adjoining_start_exit():
    plan = base_plan(start={"row": 1, "col": 1}, exit={"row": 1, "col": 2})
    res = post_plan(plan)
    assert res.status_code == 200
    data = res.json()
    assert data["steps"] == 1
    assert data["distanceMeters"] == 0.5
    assert len(data["path"]) == 2


# ---------- 费力通行格（加权搜索） ----------

def test_travel_cost_present_and_equals_steps_without_difficult_cells():
    res = post_plan(base_plan())
    data = res.json()
    assert res.status_code == 200
    # 无费力格：通行代价 = 步数
    assert data["travelCost"] == data["steps"] == 4


def test_difficult_cells_make_longer_detour_cheaper():
    """2 行 × 4 列：直走顶排要穿过两格费力格（代价 7），
    绕底排步数更多但代价更低（代价 5），应选择绕行。"""
    plan = {
        "rows": 2,
        "cols": 4,
        "start": {"row": 0, "col": 0},
        "exit": {"row": 0, "col": 3},
        "blocked": [],
        "difficultCells": [
            {"row": 0, "col": 1},
            {"row": 0, "col": 2},
        ],
    }
    res = post_plan(plan)
    assert res.status_code == 200
    data = res.json()
    path = [(c["row"], c["col"]) for c in data["path"]]
    # 下、右、右、右、上 —— 5 步绕开两格费力格
    assert path == [
        (0, 0), (1, 0), (1, 1), (1, 2), (1, 3), (0, 3)
    ]
    assert data["steps"] == 5
    assert data["distanceMeters"] == 2.5
    assert data["travelCost"] == 5  # 5 步全部普通格
    assert all(c not in {(0, 1), (0, 2)} for c in path)


def test_equal_cost_routes_break_tie_by_up_right_down_left():
    """3x3，仅中心 (1,1) 为费力格：

    沿顶排再贴右边下行（右右下下）与沿左列再贴底排右行（下下右右）
    都绕过中心、均为 4 步、代价同为 4；其余 4 步路线必踩中心（代价 6）。
    等代价时按上右下左，约定稳定命中 右右下下。
    """
    plan = base_plan(difficultCells=[{"row": 1, "col": 1}])
    res = post_plan(plan)
    assert res.status_code == 200
    data = res.json()
    path = [(c["row"], c["col"]) for c in data["path"]]
    assert path == [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)]
    assert data["steps"] == 4
    assert data["travelCost"] == 4


def test_entering_difficult_cell_costs_three():
    """2x2，起点 (0,0)、出口 (1,1)，(1,0) 为费力格。

    “下、右”进入费力格代价 1+3=4；“右、下”全普通代价 1+1=2，
    故选择步数相同但代价更低的 右、下。
    """
    plan = {
        "rows": 2,
        "cols": 2,
        "start": {"row": 0, "col": 0},
        "exit": {"row": 1, "col": 1},
        "difficultCells": [{"row": 1, "col": 0}],
    }
    res = post_plan(plan)
    assert res.status_code == 200
    data = res.json()
    assert [(c["row"], c["col"]) for c in data["path"]] == [
        (0, 0), (0, 1), (1, 1)
    ]
    assert data["steps"] == 2
    assert data["travelCost"] == 2


def test_direct_path_paying_difficult_cell_chosen_when_detour_impossible():
    """2x3：底排全阻挡，顶排唯一通道含一格费力格，必须进入，代价按 3 计。"""
    plan = {
        "rows": 2,
        "cols": 3,
        "start": {"row": 0, "col": 0},
        "exit": {"row": 0, "col": 2},
        "blocked": [{"row": 1, "col": 0}, {"row": 1, "col": 1}, {"row": 1, "col": 2}],
        "difficultCells": [{"row": 0, "col": 1}],
    }
    res = post_plan(plan)
    assert res.status_code == 200
    data = res.json()
    assert [(c["row"], c["col"]) for c in data["path"]] == [
        (0, 0), (0, 1), (0, 2)
    ]
    assert data["steps"] == 2
    assert data["travelCost"] == 1 + 3  # 普通 + 费力


def test_difficult_cells_do_not_change_unreachable_outcome():
    # 围墙封闭起点；费力格不影响可达性，结论仍为不可达
    blocked = [{"row": 0, "col": 1}, {"row": 1, "col": 0}]
    plan = base_plan(blocked=blocked, difficultCells=[{"row": 2, "col": 1}])
    res = post_plan(plan)
    data = res.json()
    assert res.status_code == 200
    assert data["reachable"] is False
    assert data["path"] == []
    assert data["travelCost"] is None
    assert data["exploredCount"] == 1


def test_omitted_difficult_cells_keeps_legacy_response_shape():
    """旧请求（无 difficultCells 字段）：四方向最短步数，路线/已探索一致，
    且成功响应仍附带 travelCost（=步数）。"""
    legacy = {
        "rows": 3,
        "cols": 3,
        "start": {"row": 0, "col": 0},
        "exit": {"row": 2, "col": 2},
        "blocked": [],
    }
    res = post_plan(legacy)
    data = res.json()
    assert [(c["row"], c["col"]) for c in data["path"]] == [
        (0, 0), (0, 1), (0, 2), (1, 2), (2, 2)
    ]
    assert data["steps"] == 4
    assert data["travelCost"] == 4


# ---------- 费力格 422 字段级错误（定位到索引，不带路线） ----------

def test_difficult_cell_out_of_bounds_field_indexed():
    plan = base_plan(difficultCells=[{"row": 0, "col": 9}])
    res = post_plan(plan)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "path" not in res.json()
    assert any(e["field"] == "difficultCells.0" and "越界" in e["message"] for e in detail)


def test_duplicate_difficult_cells_field_indexed():
    plan = base_plan(
        difficultCells=[{"row": 1, "col": 1}, {"row": 1, "col": 1}]
    )
    res = post_plan(plan)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(e["field"] == "difficultCells.1" and "重复" in e["message"] for e in detail)


def test_difficult_cell_on_start_exit_blocked_indexed():
    # 索引 0 落在起点，索引 1 落在出口，索引 2 与阻挡格重合
    plan = base_plan(
        blocked=[{"row": 2, "col": 0}],
        difficultCells=[
            {"row": 0, "col": 0},  # 起点
            {"row": 2, "col": 2},  # 出口
            {"row": 2, "col": 0},  # 阻挡格
        ],
    )
    res = post_plan(plan)
    assert res.status_code == 422
    fields = {e["field"] for e in res.json()["detail"]}
    assert "difficultCells.0" in fields
    assert "difficultCells.1" in fields
    assert "difficultCells.2" in fields
    assert "path" not in res.json()


def test_difficult_cell_wrong_type_uses_alias_path():
    plan = base_plan(difficultCells=[{"row": "x", "col": 0}])
    res = post_plan(plan)
    assert res.status_code == 422
    assert any(
        e["field"] == "difficultCells.0.row" for e in res.json()["detail"]
    )


def test_empty_difficult_cells_list_is_accepted():
    plan = base_plan(difficultCells=[])
    res = post_plan(plan)
    assert res.status_code == 200
    assert res.json()["travelCost"] == 4


# ---------- 不可达 ----------

def test_unreachable_returns_real_explored_count_and_no_path():
    # 围墙封闭左上角的起点 (0,0)
    blocked = [{"row": 0, "col": 1}, {"row": 1, "col": 0}]
    res = post_plan(base_plan(blocked=blocked))
    assert res.status_code == 200
    data = res.json()
    assert data["reachable"] is False
    assert data["path"] == []
    assert data["steps"] is None
    assert data["distanceMeters"] is None
    assert data["exploredCount"] == 1  # 只有起点被探索
    assert data["explored"] == [{"row": 0, "col": 0}]
    assert "不可达" in data["message"]


def test_unreachable_larger_explored_region():
    # 起点被一堵竖墙封在左侧列区域： explored 为真实非零值
    plan = {
        "rows": 4,
        "cols": 4,
        "start": {"row": 0, "col": 0},
        "exit": {"row": 0, "col": 3},
        "blocked": [{"row": r, "col": 1} for r in range(4)],
    }
    res = post_plan(plan)
    data = res.json()
    assert res.status_code == 200
    assert data["reachable"] is False
    assert data["exploredCount"] == 4  # 左列 4 格全部可达且被探索
    assert data["path"] == []


# ---------- 422 字段级错误 ----------

def test_rows_out_of_range():
    res = post_plan(base_plan(rows=1))
    assert res.status_code == 422
    fields = {e["field"]: e["message"] for e in res.json()["detail"]}
    assert "rows" in fields
    assert "2" in fields["rows"]

    res = post_plan(base_plan(rows=41))
    assert res.status_code == 422
    assert any(e["field"] == "rows" for e in res.json()["detail"])


def test_cols_out_of_range():
    plan_2x2 = base_plan(
        rows=2,
        cols=2,
        start={"row": 0, "col": 0},
        exit={"row": 1, "col": 1},
    )
    res = post_plan(plan_2x2)
    assert res.status_code == 200
    res = post_plan(base_plan(cols=1))
    assert res.status_code == 422
    assert res.json()["detail"][0]["field"] == "cols"


def test_start_out_of_bounds_fails_entire_request():
    plan = base_plan(start={"row": 3, "col": 0})
    res = post_plan(plan)
    assert res.status_code == 422
    data = res.json()
    assert all("path" not in e for e in data["detail"])
    fields = {e["field"] for e in data["detail"]}
    assert "start" in fields
    assert "越界" in data["detail"][0]["message"] or any(
        "越界" in e["message"] for e in data["detail"]
    )


def test_exit_out_of_bounds():
    plan = base_plan(exit={"row": 0, "col": 9})
    res = post_plan(plan)
    assert res.status_code == 422
    assert any(e["field"] == "exit" and "越界" in e["message"] for e in res.json()["detail"])


def test_start_equals_exit():
    plan = base_plan(start={"row": 1, "col": 1}, exit={"row": 1, "col": 1})
    res = post_plan(plan)
    assert res.status_code == 422
    assert any(
        e["field"] == "exit" and "同一个格" in e["message"]
        for e in res.json()["detail"]
    )


def test_start_on_blocked():
    plan = base_plan(blocked=[{"row": 0, "col": 0}])
    res = post_plan(plan)
    assert res.status_code == 422
    assert any(
        e["field"] == "start" and "阻挡格" in e["message"]
        for e in res.json()["detail"]
    )


def test_exit_on_blocked():
    plan = base_plan(blocked=[{"row": 2, "col": 2}])
    res = post_plan(plan)
    assert res.status_code == 422
    assert any(e["field"] == "exit" for e in res.json()["detail"])


def test_blocked_coordinate_out_of_bounds():
    plan = base_plan(blocked=[{"row": 0, "col": 5}])
    res = post_plan(plan)
    assert res.status_code == 422
    assert any(e["field"] == "blocked" and "越界" in e["message"] for e in res.json()["detail"])


def test_duplicate_blocked_cells_rejected():
    plan = base_plan(
        blocked=[{"row": 1, "col": 1}, {"row": 1, "col": 1}]
    )
    res = post_plan(plan)
    assert res.status_code == 422
    assert any("重复" in e["message"] for e in res.json()["detail"])


def test_multiple_errors_reported_together():
    plan = base_plan(
        rows=2,
        cols=2,
        start={"row": 0, "col": 0},
        exit={"row": 0, "col": 0},
        blocked=[{"row": 0, "col": 0}, {"row": 0, "col": 0}],
    )
    res = post_plan(plan)
    assert res.status_code == 422
    fields = {e["field"] for e in res.json()["detail"]}
    assert "exit" in fields      # 起终点重合
    assert "start" in fields     # 起点被阻挡
    assert "blocked" in fields   # 阻挡重复


def test_missing_field():
    res = client.post("/api/shortest-path", json={"rows": 3, "cols": 3})
    assert res.status_code == 422
    fields = {e["field"] for e in res.json()["detail"]}
    assert "start" in fields
    assert "exit" in fields


def test_wrong_type_field():
    res = post_plan(base_plan(rows="三"))
    assert res.status_code == 422
    assert any(e["field"] == "rows" for e in res.json()["detail"])


def test_extra_field_rejected():
    res = post_plan(base_plan(unknown=123))
    assert res.status_code == 422
    assert any("多余字段" in e["message"] for e in res.json()["detail"])


def test_body_not_object():
    res = client.post("/api/shortest-path", json=[1, 2, 3])
    assert res.status_code == 422
    assert res.json()["detail"][0]["field"] == "body"


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
