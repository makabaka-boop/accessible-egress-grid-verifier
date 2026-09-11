# 社区礼堂轮椅疏散路线核验器

一个全栈核验工具：核验员在 React 网格编辑器中绘制改造中礼堂的方格平面
（2–40 行 × 2–40 列，恰好一个起点、一个出口、若干阻挡格），前端将结构化
平面提交给 FastAPI，后端自行实现四方向 BFS 最短路径搜索，返回**唯一**的
有序坐标路线与步数。

- 每格边长 **0.5 米**；**起点计入路线但不计步**。
- 只能向上、下、左、右进入**非阻挡格**，不能斜向移动。
- 存在多条等长最短路线时，相邻格扩展顺序固定为
  **上 → 右 → 下 → 左**，由 BFS 入队顺序保证结果唯一。
- 出口不可达时明确返回“不可达”，给出真实的已探索格数（≥1），
  且前端画布不绘制任何路线。

## 目录结构

```
api/                 FastAPI + Pydantic + 自研 BFS
  app/main.py           路由与统一的字段级错误响应
  app/models.py         请求模型（结构校验）
  app/validation.py     语义校验（越界/重合/阻挡）
  app/pathfinding.py    四方向 BFS（上→右→下→左）
  tests/test_api.py     pytest（22 个用例）
web/                 React + TypeScript + Vite
  src/lib/grid.ts       纯函数：网格编辑、提交前校验（vitest 覆盖）
  src/lib/api.ts        API 客户端：422 转字段级错误
  src/components/       网格编辑器、错误面板、结果面板
  e2e/app.e2e.ts        Playwright 端到端（可达 / 不可达 / 422）
verify/              一次性验收服务（Dockerfile）
scripts/             verify-local.sh 与 HTTP 契约冒烟脚本
docker-compose.yml   web、api 与 verify 三个服务
```

## 一、用 Docker Compose 运行（推荐）

```bash
# 默认宿主端口：web 8080、api 8000
docker compose up --build web api

# 覆盖宿主端口
WEB_PORT=9090 API_PORT=9000 docker compose up --build web api
```

打开 http://localhost:8080 （端口被覆盖时换成 `$WEB_PORT`）。
web 容器内的 nginx 会把 `/api/*` 反向代理到 api 容器，前端无需配置地址。

### 一次性验收服务 verify

`verify` 是一个跑完即退出的服务，依次执行：
**pytest → vitest → 真实 HTTP 契约冒烟 → Playwright e2e**，
全部通过退出码为 0，任一失败立即非零退出：

```bash
docker compose build verify
docker compose run --rm verify
```

它通过 compose 的健康检查等待 api/web 就绪后才开始，打的是运行中的真实
容器（不是固定响应、不是 mock）。

## 二、本地（无 Docker）运行与验收

前置：Node.js ≥ 20、Python ≥ 3.11。

```bash
# 后端
pip install -r api/requirements-dev.txt
(cd api && uvicorn app.main:app --reload --port 8000)

# 前端（dev server 自动把 /api 代理到 127.0.0.1:8000）
(cd web && npm install && npm run dev)
```

一键本地验收（自动拉起 api 与 web，跑完自动关闭）：

```bash
WEB_PORT=8080 API_PORT=8000 bash scripts/verify-local.sh
```

单独跑测试：

```bash
(cd api && python -m pytest)          # 后端
(cd web && npm test)                  # vitest 单元测试
(cd web && npm run typecheck)         # tsc --noEmit
(cd web && npm run e2e)               # Playwright（需先启动 api、web）
```

## 三、请求契约

### `POST /api/shortest-path`

请求体（JSON）：

| 字段      | 类型             | 约束                                                         |
| --------- | ---------------- | ------------------------------------------------------------ |
| `rows`    | integer          | 2 ≤ rows ≤ 40                                                |
| `cols`    | integer          | 2 ≤ cols ≤ 40                                                |
| `start`   | `{row, col}`     | 0 基坐标，必须在网格内，不能被阻挡                           |
| `exit`    | `{row, col}`     | 0 基坐标，必须在网格内，不能被阻挡、不能与起点重合           |
| `blocked` | `[{row, col}, …]` | 可选；坐标必须在网格内、不得重复                             |

多余字段一律拒绝（`extra_forbid`）。坐标均为 **0 基 [row, col]**。

请求示例：

```json
{
  "rows": 3,
  "cols": 3,
  "start": { "row": 0, "col": 0 },
  "exit": { "row": 2, "col": 2 },
  "blocked": [{ "row": 0, "col": 1 }]
}
```

#### 成功响应 `200` —— 可达

```json
{
  "reachable": true,
  "message": "找到唯一最短路线",
  "path": [
    {"row": 0, "col": 0}, {"row": 1, "col": 0},
    {"row": 2, "col": 0}, {"row": 2, "col": 1},
    {"row": 2, "col": 2}
  ],
  "steps": 4,
  "distanceMeters": 2.0,
  "exploredCount": 9,
  "explored": [ "…BFS 实际访问顺序的坐标…" ]
}
```

`steps = path.length - 1`（起点计入路线但不计步），
`distanceMeters = steps × 0.5`。

#### 成功响应 `200` —— 不可达

```json
{
  "reachable": false,
  "message": "不可达：在当前阻挡布局下，没有任何四方向路线可以从起点到达出口",
  "path": [],
  "steps": null,
  "distanceMeters": null,
  "exploredCount": 1,
  "explored": [{ "row": 1, "col": 1 }]
}
```

`exploredCount` 始终为真实值：出口不可达时 ≥ 1（起点必被探索），绝不会是 0。

#### 失败响应 `422` —— 整次请求失败，不返回任何路线

行列不符、坐标越界、起终点重合、起点/出口被阻挡、阻挡格重复、
类型错误、缺字段、多余字段等，统一返回：

```json
{
  "detail": [
    { "field": "start", "message": "起点位于阻挡格上，疏散路线无法开始" },
    { "field": "exit",  "message": "出口与起点不能是同一个格" }
  ]
}
```

- `field` 为字段路径，如 `rows`、`blocked.2.col`，可直接定位到表单项或格；
- 多条错误会一次性全部返回；
- 响应中**不含** `path`，前端会清空画布，绝不残留上一次成功路线。

健康检查：`GET /api/health` → `{"status":"ok"}`。

## 四、前端行为约定（核验员视角）

1. 选择工具（① 起点 / ② 出口 / ③ 阻挡 / 橡皮）后点击格放置；
   起点、出口各只有一个，再次放置即移动；阻挡不能压在起终点上。
2. 点「核验最短疏散路线」后：
   - **成功**：蓝色绘制唯一最短路线，显示步数与米数，可展开有序坐标；
   - **不可达**：琥珀色面板明确显示“不可达”与真实已探索格数，
     灰色标出实际探索范围，画布上没有任何路线；
   - **请求失败**：红色面板按字段列出可操作的中文错误；
3. 任何一次对平面的编辑（含改尺寸、放格、擦除）都会立即作废上一次结果，
   画布不残留旧轨迹。
