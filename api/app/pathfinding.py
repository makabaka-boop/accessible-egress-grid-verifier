"""四方向最短路径搜索（BFS）。

规则：
* 只能向上、右、下、左移动到非阻挡格；
* 相邻格的扩展顺序固定为 上 → 右 → 下 → 左，
  因此存在多条等长最短路线时，由该顺序唯一确定一条；
* 起点计入路线但不计步；
* 每格边长 0.5 米。
"""

from __future__ import annotations

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


def find_shortest_path(
    plan: GridPlan,
) -> tuple[list[tuple[int, int]] | None, list[tuple[int, int]], int]:
    """执行 BFS。

    返回 ``(path, explored_order, explored_count)``：
    出口可达时 ``path`` 为从起点到出口的有序坐标；
    不可达时 ``path`` 为 ``None``，但 ``explored_order`` 仍包含真实的
    已探索格（起点始终在内，不可达时至少为 1）。
    """

    start = plan.start.as_tuple()
    target = plan.exit.as_tuple()
    blocked = {cell.as_tuple() for cell in plan.blocked}

    queue: deque[tuple[int, int]] = deque([start])
    parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    explored_order: list[tuple[int, int]] = [start]

    reachable = False
    while queue:
        current = queue.popleft()
        if current == target:
            reachable = True
            break
        r, c = current
        for dr, dc, _name in DIRECTIONS:
            neighbor = (r + dr, c + dc)
            nr, nc = neighbor
            if not (0 <= nr < plan.rows and 0 <= nc < plan.cols):
                continue
            if neighbor in blocked or neighbor in parents:
                continue
            parents[neighbor] = current
            explored_order.append(neighbor)
            queue.append(neighbor)

    if not reachable:
        return None, explored_order, len(explored_order)

    # 从出口沿 parent 回溯，再反转为起点 → 出口
    path_reversed: list[tuple[int, int]] = []
    node: tuple[int, int] | None = target
    while node is not None:
        path_reversed.append(node)
        node = parents[node]
    path = list(reversed(path_reversed))
    return path, explored_order, len(explored_order)
