"""四方向最短路径搜索。

规则：
* 只能向上、右、下、左移动到非阻挡格；
* 相邻格的扩展顺序固定为 上 → 右 → 下 → 左；
* 起点计入路线但不计步；
* 每格边长 0.5 米；
* 普通移动代价为 1，进入费力通行格的代价为 3
  （起点不付费；代价附在“进入该格”的移动上）。

寻路分两层：
1. **可达性与已探索顺序**：永远先跑一次忽略权重（费力格仍可通行）的
   原四方向 BFS。它既给出“不可达”结论与真实已探索范围，也在**无费力格**
   时直接作为最终结果，路线与已探索顺序与旧版逐格一致。
2. **含费力格时的最优路线**：从出口沿反向图做 Dijkstra，求每格到出口的
   最优标签 ``(最小代价, 最少步数)``；再从起点出发，按 上 → 右 → 下 → 左
   依次考察邻居，贪心选择“第一个可构成最优续接”的邻居。
   这样在总代价相同、步数也相同的多条路线中，得到的正是第一个分歧方向上
   更靠前（上 < 右 < 下 < 左）的那条，结果确定且唯一。
"""

from __future__ import annotations

import heapq
from collections import deque

from .models import GridPlan

# (dr, dc)，顺序即扩展优先级：上、右、下、左
DIRECTIONS: tuple[tuple[int, int, str], ...] = (
    (-1, 0, "上"),
    (0, 1, "右"),
    (1, 0, "下"),
    (0, -1, "左"),
)

CELL_SIZE_METERS = 0.5
DIFFICULT_COST = 3
NORMAL_COST = 1

_INF: int = 10**18


def _reconstruct(
    parents: dict[tuple[int, int], tuple[int, int] | None],
    target: tuple[int, int],
) -> list[tuple[int, int]]:
    """从出口沿 parent 回溯，再反转为起点 → 出口。"""

    path_reversed: list[tuple[int, int]] = []
    node: tuple[int, int] | None = target
    while node is not None:
        path_reversed.append(node)
        node = parents[node]
    return list(reversed(path_reversed))


def _neighbors_in_order(
    plan: GridPlan,
    current: tuple[int, int],
    blocked: set[tuple[int, int]],
):
    """按 上 → 右 → 下 → 左 生成在网格内且非阻挡的相邻格。"""

    r, c = current
    for dr, dc, _name in DIRECTIONS:
        neighbor = (r + dr, c + dc)
        nr, nc = neighbor
        if not (0 <= nr < plan.rows and 0 <= nc < plan.cols):
            continue
        if neighbor in blocked:
            continue
        yield neighbor


def _find_unweighted(
    plan: GridPlan,
    start: tuple[int, int],
    target: tuple[int, int],
    blocked: set[tuple[int, int]],
) -> tuple[list[tuple[int, int]] | None, list[tuple[int, int]]]:
    """原四方向 BFS（忽略费力代价）：定可达性、已探索顺序；无费力格时即最终路线。"""

    queue: deque[tuple[int, int]] = deque([start])
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    explored_order: list[tuple[int, int]] = [start]

    reachable = False
    while queue:
        current = queue.popleft()
        if current == target:
            reachable = True
            break
        for neighbor in _neighbors_in_order(plan, current, blocked):
            if neighbor in parents:
                continue
            parents[neighbor] = current
            explored_order.append(neighbor)
            queue.append(neighbor)

    if not reachable:
        return None, explored_order
    return _reconstruct(parents, target), explored_order


def _enter_cost(cell: tuple[int, int], difficult: set[tuple[int, int]]) -> int:
    return DIFFICULT_COST if cell in difficult else NORMAL_COST


def _weighted_optimal_path(
    plan: GridPlan,
    start: tuple[int, int],
    target: tuple[int, int],
    blocked: set[tuple[int, int]],
    difficult: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    """含费力格时求 (最小代价, 最少步数, 上右下左最早) 的唯一路线。

    前置：``start`` 经非阻挡格可到达 ``target``（已由 BFS 确认）。
    """

    # --- 反向 Dijkstra：cost[u] / steps[u] 为 u 到出口的最优 (代价, 步数) ---
    # 反向边 v -> u（对应原移动 u -> v）的权为“进入 v 的代价”。
    cost: dict[tuple[int, int], int] = {target: 0}
    steps: dict[tuple[int, int], int] = {target: 0}
    # 堆条目：(代价, 步数, 节点)；步数是第二关键字，只需保证标签按字典序最优
    heap: list[tuple[int, int, tuple[int, int]]] = [(0, 0, target)]

    while heap:
        cur_cost, cur_steps, current = heapq.heappop(heap)
        if (cur_cost, cur_steps) != (cost[current], steps[current]):
            continue  # 过期条目
        w_enter_current = _enter_cost(current, difficult)
        for neighbor in _neighbors_in_order(plan, current, blocked):
            # 原移动 neighbor -> current：进入 current 需付 w_enter_current
            new_cost = cur_cost + w_enter_current
            new_steps = cur_steps + 1
            old = (cost.get(neighbor, _INF), steps.get(neighbor, _INF))
            if (new_cost, new_steps) < old:
                cost[neighbor] = new_cost
                steps[neighbor] = new_steps
                heapq.heappush(heap, (new_cost, new_steps, neighbor))

    # --- 从起点按 上右下左贪心：选第一个可构成最优续接的邻居 ---
    path = [start]
    current = start
    while current != target:
        chosen: tuple[int, int] | None = None
        for neighbor in _neighbors_in_order(plan, current, blocked):
            w_enter_neighbor = _enter_cost(neighbor, difficult)
            if (
                cost[current] == cost.get(neighbor, _INF) + w_enter_neighbor
                and steps[current] == steps.get(neighbor, _INF) + 1
            ):
                chosen = neighbor
                break
        if chosen is None:  # 理论不可达：BFS 已确认连通，这里仅作防御
            raise RuntimeError("加权路线重建失败：起点应可到达出口")
        path.append(chosen)
        current = chosen
    return path


def find_shortest_path(
    plan: GridPlan,
) -> tuple[list[tuple[int, int]] | None, list[tuple[int, int]], int]:
    """执行搜索。

    返回 ``(path, explored_order, explored_count)``：
    出口可达时 ``path`` 为从起点到出口的有序坐标；
    不可达时 ``path`` 为 ``None``，但 ``explored_order`` 仍包含真实的
    已探索格（起点始终在内，不可达时至少为 1）。

    无费力格时直接采用 BFS 路线，保证旧请求的路线与已探索顺序完全不变。
    """

    start = plan.start.as_tuple()
    target = plan.exit.as_tuple()
    blocked = {cell.as_tuple() for cell in plan.blocked}
    difficult = {cell.as_tuple() for cell in (plan.difficult_cells or [])}

    # 可达性与已探索范围由忽略权重的 BFS 决定（费力格始终可通行）
    path, explored_order = _find_unweighted(plan, start, target, blocked)
    if path is None:
        return None, explored_order, len(explored_order)

    if difficult:
        path = _weighted_optimal_path(plan, start, target, blocked, difficult)

    return path, explored_order, len(explored_order)


def path_travel_cost(
    path: list[tuple[int, int]], difficult: set[tuple[int, int]]
) -> int:
    """路线的累计通行代价：起点不计；进入费力格为 3，其余为 1。"""

    return sum(
        DIFFICULT_COST if cell in difficult else NORMAL_COST for cell in path[1:]
    )
