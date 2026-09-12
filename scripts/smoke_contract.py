#!/usr/bin/env python3
"""对已启动的 api 与 web 容器做真实 HTTP 契约冒烟（仅用标准库）。

通过环境变量指定地址：
    API_BASE_URL（默认 http://localhost:8000）
    WEB_BASE_URL（默认 http://localhost:8080）

覆盖：健康检查、可达路线、不可达（真实探索数）、422 字段级错误、
以及 web 根路径可访问且其 /api 被代理到后端。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
WEB = os.environ.get("WEB_BASE_URL", "http://localhost:8080").rstrip("/")

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def request(url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.status, resp.read().decode()


print("== api 健康检查 ==")
status, body = request(f"{API}/api/health")
check("GET /api/health 返回 200 ok", status == 200 and body.get("status") == "ok")

print("== 可达路线契约 ==")
reachable_plan = {
    "rows": 3,
    "cols": 3,
    "start": {"row": 0, "col": 0},
    "exit": {"row": 2, "col": 2},
    "blocked": [],
}
status, body = request(f"{API}/api/shortest-path", reachable_plan)
check("可达时 status=200 reachable=true", status == 200 and body.get("reachable") is True)
check("步数为 4、距离 2.0 米", body.get("steps") == 4 and body.get("distanceMeters") == 2.0)
check(
    "路线有序且首尾正确",
    body.get("path", [{}])[0] == {"row": 0, "col": 0}
    and body.get("path", [{}])[-1] == {"row": 2, "col": 2},
)
check(
    "扩展顺序上右下左 → 右右下下",
    [(c["row"], c["col"]) for c in body.get("path", [])]
    == [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)],
)
check("无费力格时 travelCost 等于步数 4", body.get("travelCost") == 4)

print("== 费力通行格：更长绕行代价更低 ==")
detour_plan = {
    "rows": 2,
    "cols": 4,
    "start": {"row": 0, "col": 0},
    "exit": {"row": 0, "col": 3},
    "blocked": [],
    "difficultCells": [{"row": 0, "col": 1}, {"row": 0, "col": 2}],
}
status, body = request(f"{API}/api/shortest-path", detour_plan)
check("费力格请求 status=200", status == 200 and body.get("reachable") is True)
check(
    "选择 5 步绕底排路线（代价 5）而非 3 步直线（代价 7）",
    body.get("steps") == 5
    and body.get("travelCost") == 5
    and [(c["row"], c["col"]) for c in body.get("path", [])]
    == [(0, 0), (1, 0), (1, 1), (1, 2), (1, 3), (0, 3)],
)

print("== 费力格：等代价按上右下左稳定 ==")
tie_plan = {
    "rows": 3,
    "cols": 3,
    "start": {"row": 0, "col": 0},
    "exit": {"row": 2, "col": 2},
    "difficultCells": [{"row": 1, "col": 1}],
}
status, body = request(f"{API}/api/shortest-path", tie_plan)
check(
    "等代价稳定命中 右右下下，travelCost=4",
    body.get("travelCost") == 4
    and [(c["row"], c["col"]) for c in body.get("path", [])]
    == [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)],
)

print("== 费力格非法：422 定位到索引且无路线 ==")
overlap_plan = {
    "rows": 3,
    "cols": 3,
    "start": {"row": 0, "col": 0},
    "exit": {"row": 2, "col": 2},
    "blocked": [{"row": 2, "col": 0}],
    "difficultCells": [
        {"row": 0, "col": 0},  # 0: 落在起点
        {"row": 2, "col": 2},  # 1: 落在出口
        {"row": 2, "col": 0},  # 2: 与阻挡格重合
        {"row": 9, "col": 9},  # 3: 越界
    ],
}
status, body = request(f"{API}/api/shortest-path", overlap_plan)
detail = body.get("detail", [])
check("费力格非法返回 422", status == 422)
check("422 不含 path 字段", "path" not in body)
idx_fields = {e.get("field") for e in detail}
check(
    "错误定位到 difficultCells.0/1/2/3",
    {"difficultCells.0", "difficultCells.1", "difficultCells.2", "difficultCells.3"}
    <= idx_fields,
    str(idx_fields),
)

print("== 旧请求省略 difficultCells 字段：响应与字段兼容 ==")
status, body = request(f"{API}/api/shortest-path", reachable_plan)
check("旧请求仍可达且步数 4", status == 200 and body.get("steps") == 4)
check(
    "旧请求路线仍是 右右下下",
    [(c["row"], c["col"]) for c in body.get("path", [])]
    == [(0, 0), (0, 1), (0, 2), (1, 2), (2, 2)],
)

print("== 不可达契约 ==")
unreachable_plan = {
    "rows": 4,
    "cols": 4,
    "start": {"row": 0, "col": 0},
    "exit": {"row": 0, "col": 3},
    "blocked": [{"row": r, "col": 1} for r in range(4)],
}
status, body = request(f"{API}/api/shortest-path", unreachable_plan)
check("不可达时 status=200 reachable=false", status == 200 and body.get("reachable") is False)
check("不可达不返回路线", body.get("path") == [] and body.get("steps") is None)
check("不可达时 travelCost 为 null", body.get("travelCost") is None)
check(
    "已探索格数为非零真实值 4",
    isinstance(body.get("exploredCount"), int) and body["exploredCount"] == 4,
)
check("提示包含“不可达”", "不可达" in body.get("message", ""))

print("== 422 字段级错误契约 ==")
bad_plan = {
    "rows": 3,
    "cols": 3,
    "start": {"row": 0, "col": 0},
    "exit": {"row": 0, "col": 0},
    "blocked": [{"row": 0, "col": 0}],
}
status, body = request(f"{API}/api/shortest-path", bad_plan)
detail = body.get("detail", [])
check("非法请求返回 422", status == 422)
check("detail 为字段级错误数组", isinstance(detail, list) and len(detail) >= 2)
fields = {e.get("field") for e in detail}
check("错误定位到 start / exit", {"start", "exit"} <= fields, str(fields))
check("错误信息为可操作中文", all(len(e.get("message", "")) > 4 for e in detail))

print("== 行列越界契约 ==")
status, body = request(
    f"{API}/api/shortest-path",
    {"rows": 41, "cols": 1, "start": {"row": 0, "col": 0}, "exit": {"row": 0, "col": 0},
     "blocked": []},
)
check("行列不符返回 422 且无路径字段", status == 422 and "path" not in body)

print("== web 容器与 /api 代理 ==")
status, html = get(f"{WEB}/")
check("web 根路径返回 HTML", status == 200 and "<div id=\"root\"" in html)
status, body = request(f"{WEB}/api/shortest-path", reachable_plan)
check("web 的 /api 反向代理到后端并返回路线", status == 200 and body.get("reachable") is True)

print("== 通行实测：创建 → 逐格推进 → 出口锁定（跨请求累积） ==")
walk_path = [
    {"row": 0, "col": 0},
    {"row": 0, "col": 1},
    {"row": 0, "col": 2},
]
status, body = request(f"{API}/api/walk-trials", {"path": walk_path})
check("创建实测 status=200", status == 200)
check(
    "创建后检查点在起点、累计 0、下一格 (0,1)、快照不可变",
    body.get("checkpoint") == 0
    and body.get("elapsedSeconds") == 0
    and body.get("totalSeconds") is None
    and body.get("nextCoordinate") == {"row": 0, "col": 1}
    and body.get("path") == walk_path
    and body.get("totalSteps") == 2,
)
trial_id = body.get("id")

status, body = request(f"{API}/api/walk-trials/{trial_id}/advance", {"seconds": 10})
check("第 1 段推进 status=200 且累计 10", status == 200 and body.get("elapsedSeconds") == 10)
check("第 1 段后下一格 (0,2)、进度 1/2", body.get("checkpoint") == 1
      and body.get("nextCoordinate") == {"row": 0, "col": 2}
      and body.get("progressPercent") == 50.0)

status, body = request(f"{API}/api/walk-trials/{trial_id}/advance", {"seconds": 25})
check("第 2 段到达出口、锁定总耗时 35", status == 200
      and body.get("completed") is True
      and body.get("totalSeconds") == 35
      and body.get("elapsedSeconds") == 35
      and body.get("nextCoordinate") is None
      and body.get("progressPercent") == 100.0)
check("逐段秒数回显并求和一致",
      [s.get("seconds") for s in body.get("segments", [])] == [10, 25])

print("== 通行实测：错误返回字段级结构且数据不变 ==")
# 完成后继续推进
status, after_lock = request(f"{API}/api/walk-trials/{trial_id}/advance", {"seconds": 7})
check("完成后推进返回 422 且定位 completed", status == 422
      and any(e.get("field") == "completed" for e in after_lock.get("detail", [])))
# 非法秒数（0 / 整值小数 / 越界）
for bad_seconds in (0, 3.0, 3601, "60"):
    code, bad_body = request(
        f"{API}/api/walk-trials/{trial_id}/advance", {"seconds": bad_seconds}
    )
    check(f"秒数 {bad_seconds!r} 返回 422 且定位 seconds",
          code == 422 and any(e.get("field") == "seconds" for e in bad_body.get("detail", [])))
# 编号不存在
status, bad_body = request(f"{API}/api/walk-trials/nonexistentid/advance", {"seconds": 10})
check("不存在编号返回 422 且定位 trialId", status == 422
      and any(e.get("field") == "trialId" for e in bad_body.get("detail", [])))
# 创建校验：路线至少两格、仅四方向
status, bad_body = request(f"{API}/api/walk-trials", {"path": [{"row": 0, "col": 0}]})
check("单格路线创建被拒（path）", status == 422
      and any(e.get("field") == "path" for e in bad_body.get("detail", [])))
status, bad_body = request(
    f"{API}/api/walk-trials",
    {"path": [{"row": 0, "col": 0}, {"row": 1, "col": 1}]},  # 斜向
)
check("斜向相邻路线创建被拒（path.1）", status == 422
      and any(e.get("field") == "path.1" for e in bad_body.get("detail", [])))

# 新建一次实测并走完，复查其锁定值，确认前面的非法推进未串改任何数据
status, body = request(f"{API}/api/walk-trials", {"path": walk_path})
other_id = body.get("id")
request(f"{API}/api/walk-trials/{other_id}/advance", {"seconds": 5})
status, body = request(f"{API}/api/walk-trials/{other_id}/advance", {"seconds": 7})
check("另一条实测独立锁定为 12，不与前一条 35 串数据",
      status == 200 and body.get("completed") is True and body.get("totalSeconds") == 12)

print("== 通行实测：两名核验员同时确认同一次实测（并发推进，不得 500/丢更新） ==")
concurrent_path = [
    {"row": 0, "col": 0},
    {"row": 0, "col": 1},
    {"row": 0, "col": 2},
]
status, body = request(f"{API}/api/walk-trials", {"path": concurrent_path})
ctid = body.get("id")


def advance_seconds(seconds: int) -> tuple[int, dict]:
    return request(f"{API}/api/walk-trials/{ctid}/advance", {"seconds": seconds})


with ThreadPoolExecutor(max_workers=2) as pool:
    c_results = list(pool.map(advance_seconds, (10, 20)))
c_status = sorted(code for code, _ in c_results)
c_final = [b for _, b in c_results if b.get("completed")]
check("并发的两个推进请求都成功（无 5xx）", c_status == [200, 200], str(c_status))
check(
    "并发后检查点前进两格、总耗时锁定 30、两段都落库",
    c_status == [200, 200]
    and len(c_final) == 1
    and c_final[0].get("totalSeconds") == 30
    and sorted(s.get("seconds") for s in c_final[0].get("segments", [])) == [10, 20],
)

print("== 通行实测经 web /api 代理同样可用 ==")
status, body = request(f"{WEB}/api/walk-trials", {"path": walk_path})
check("经 web 代理创建实测成功", status == 200 and body.get("nextCoordinate") is not None)

if failures:
    print(f"\n❌ 冒烟失败 {len(failures)} 项：{failures}")
    sys.exit(1)
print("\n✅ HTTP 契约冒烟全部通过")
