# 社区礼堂轮椅疏散路线核验器

一个全栈核验工具：核验员在 React 网格编辑器中绘制改造中礼堂的方格平面
（2–40 行 × 2–40 列，恰好一个起点、一个出口、若干阻挡格，可选若干“费力
通行格”），前端将结构化平面提交给 FastAPI，后端自行实现四方向搜索，返回
**唯一**的有序坐标路线、步数与累计通行代价。

- 每格边长 **0.5 米**；**起点计入路线但不计步**。
- 只能向上、下、左、右进入**非阻挡格**，不能斜向移动。
- **普通移动代价为 1，进入费力通行格的代价为 3**（起点不付费）。
- 优化目标依次为：**累计通行代价最低 → 步数更少 → 按 上 → 右 → 下 → 左
  扩展更早**，三者共同保证结果唯一。
- 不提交费力格（或空列表）时退化为原四方向 BFS：按最短步数选路，
  等长路线由 **上 → 右 → 下 → 左** 的入队顺序唯一确定，结果与旧版一致。
- 出口不可达时明确返回“不可达”，给出真实的已探索格数（≥1），
  且前端画布不绘制任何路线。

### 通行实测（核验通过后的独立模块）

核验通过后，核验员可基于**不可变路线快照**发起一次“通行实测”：
轮椅按路线逐格试走，每确认到达下一格就输入该段秒数（**1–3600 的整数**），
面板持续显示**下一坐标、累计时间与完成进度**；到达出口后**锁定总耗时**。
发起前可**选填单段目标秒数**（同为 1–3600 的整数）：设定后每段按
“秒数大于目标 → **超时**，否则 **达标**”逐格判定，面板即时汇总两类
段数与对应坐标；留空则不判定，行为与旧版完全一致。
现场输错某段秒数时可**撤回最后一次推进**：后端删除末段记录、回退检查点，
从剩余分段重新生成累计时间、完成状态与目标判定汇总；撤回已完成实测的
末段后记录恢复为进行中，可按正确秒数继续，不必丢弃整次实测。

- 后端在 **API 进程内用 SQLite**（`api/var/walk_trials.db`，可用环境变量
  `WALK_DB_PATH` 覆盖）保存实测记录，启动时按 `PRAGMA user_version`
  **建表迁移**（`walk_trials` 快照/检查点表 + `walk_segments` 逐段表；
  v2 起 `walk_trials` 增加 `target_seconds` 列固化目标值，历史记录为
  `NULL` 即不判定）。
- 只开放三个写接口：`POST /api/walk-trials`（创建）、
  `POST /api/walk-trials/{id}/advance`（推进检查点）与
  `POST /api/walk-trials/{id}/undo`（撤回最后一次推进），
  无任何其它修改/删除接口。
- 推进与撤回都在 `BEGIN IMMEDIATE` 立即写事务内完成（锁内重读最新检查点），
  **两名现场人员同时确认同一次实测时请求被串行化**：都成功且各前进一格，
  不会出现服务器错误或“只前进一格”的丢失更新；单段路线被两人同时确认时，
  先提交者锁定，后到者得到字段级 `completed` 422（不 5xx）。
- 创建时校验**路线至少两格且相邻坐标仅四方向移动**；推进与撤回都返回
  **完整进度**，跨请求的累计时间来自落库的逐段秒数，逐段判定来自
  **同一落库目标值**；撤回后的累计时间与判定汇总从**剩余落库分段**
  重新生成。
- 秒数非法、目标值非法、实测编号不存在、完成后继续推进、尚无已确认段
  却撤回，统一返回既有字段级错误结构（422 `detail`），且**数据不发生变化**。
- 实测反馈只留在“通行实测”面板内，**不清除也不修改原核验路线**；
  未发起实测的路线核验、费力格选路与旧响应行为完全兼容。

## 目录结构

```
api/                 FastAPI + Pydantic + 自研搜索
  app/main.py           路由与统一的字段级错误响应
  app/models.py         请求模型（结构校验，difficultCells 为可选别名）
  app/validation.py     语义校验（越界/重合/阻挡/费力格）
  app/pathfinding.py    BFS（可达性/无费力格）+ 确定性加权搜索（费力格）
  app/walk_models.py    通行实测创建模型（路线快照 + 可选单段目标秒数）
  app/walk.py           SQLite 建表迁移 + 实测创建/推进/撤回三个写操作
  tests/test_api.py     pytest（核验接口）
  tests/test_walk.py    pytest（通行实测：跨请求累积、最终落库、撤回重录、422 不变数据）
web/                 React + TypeScript + Vite
  src/lib/grid.ts       纯函数：网格编辑、提交前校验（vitest 覆盖）
  src/lib/api.ts        API 客户端：核验 + 实测创建/推进/撤回，422 转字段级错误
  src/components/       网格编辑器、错误面板、结果面板、通行实测面板
  e2e/app.e2e.ts        Playwright 端到端（可达 / 不可达 / 422 / 核验贯通实测）
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
| `difficultCells` | `[{row, col}, …]` | 可选；费力通行格，进入代价为 3。坐标必须在网格内、不得重复，且不能落在起点、出口或阻挡格上；省略与 `[]` 等价，显式 `null` 按类型错误拒绝 |

多余字段一律拒绝（`extra_forbid`）。坐标均为 **0 基 [row, col]**。
所有整数字段（`rows`、`cols`、各坐标的 `row`/`col`）只接受 JSON 整数：
整值小数（如 `3.0`）、布尔、数字字符串一律按类型错误拒绝，不做静默转换。

请求示例：

```json
{
  "rows": 3,
  "cols": 3,
  "start": { "row": 0, "col": 0 },
  "exit": { "row": 2, "col": 2 },
  "blocked": [{ "row": 0, "col": 1 }],
  "difficultCells": [{ "row": 2, "col": 1 }]
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
  "travelCost": 4,
  "exploredCount": 9,
  "explored": [ "…BFS 实际访问顺序的坐标…" ]
}
```

`steps = path.length - 1`（起点计入路线但不计步），
`distanceMeters = steps × 0.5`，
`travelCost` 为累计通行代价：起点不计，进入普通格 1、进入费力格 3；
不含费力格时 `travelCost == steps`。

#### 成功响应 `200` —— 不可达

```json
{
  "reachable": false,
  "message": "不可达：在当前阻挡布局下，没有任何四方向路线可以从起点到达出口",
  "path": [],
  "steps": null,
  "distanceMeters": null,
  "travelCost": null,
  "exploredCount": 1,
  "explored": [{ "row": 1, "col": 1 }]
}
```

`exploredCount` 始终为真实值：出口不可达时 ≥ 1（起点必被探索），绝不会是 0。

#### 失败响应 `422` —— 整次请求失败，不返回任何路线

行列不符、坐标越界、起终点重合、起点/出口被阻挡、阻挡格重复、
费力格越界/重复/落在起点·出口·阻挡格上、类型错误、缺字段、多余字段等，
统一返回：

```json
{
  "detail": [
    { "field": "start", "message": "起点位于阻挡格上，疏散路线无法开始" },
    { "field": "difficultCells.0",  "message": "费力通行格不能标记在起点上" }
  ]
}
```

- `field` 为字段路径，如 `rows`、`blocked.2.col`、`difficultCells.0`，
  可直接定位到表单项或列表中的具体格；
- 多条错误会一次性全部返回；
- 响应中**不含** `path`，前端会清空画布，绝不残留上一次成功路线。

健康检查：`GET /api/health` → `{"status":"ok"}`。

### `POST /api/walk-trials`（创建通行实测）

以一次成功核验返回的有序路线作为**不可变快照**创建实测，
可选携带**单段目标秒数**：

```json
{ "path": [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
  "targetSeconds": 15 }
```

- `path` 至少 2 格；相邻坐标必须**仅四方向移动**（曼哈顿距离 1），
  斜向、跳格、原地都按 `path.<索引>` 字段错误拒绝；坐标仍须为严格整数。
- `targetSeconds` **可选**：1–3600 的整数，随实测记录落库后不再改变，
  用于把每段判定为超时/达标；省略（旧客户端）表示不判定，
  显式 `null`、布尔、字符串、整值小数、越界整数一律按
  `targetSeconds` 字段错误拒绝，且**不产生实测记录**。
- 成功 `200` 返回完整进度（见下），创建时 `checkpoint=0`、
  `elapsedSeconds=0`、`totalSeconds=null`、`nextCoordinate=path[1]`。

### `POST /api/walk-trials/{id}/advance`（推进检查点）

```json
{ "seconds": 12 }
```

确认轮椅从上一格进入下一格用了 `seconds` 秒（**1–3600 的整数**），
服务端只做一次 INSERT 并推进检查点，返回推进后的**完整进度**。
走完最后一段时 `completed=true`、`totalSeconds` 锁定为各段之和。

进度响应（创建/推进共用）：

```json
{
  "id": "…", "status": "in_progress",
  "path": [{"row": 0, "col": 0}, {"row": 0, "col": 1}, {"row": 0, "col": 2}],
  "totalSteps": 2, "checkpoint": 1,
  "nextCoordinate": {"row": 0, "col": 2},
  "elapsedSeconds": 12, "totalSeconds": null,
  "targetSeconds": 15,
  "verdictSummary": {
    "onTargetCount": 1, "overtimeCount": 0,
    "onTargetCoordinates": [{"row": 0, "col": 1}],
    "overtimeCoordinates": []
  },
  "progressPercent": 50.0, "remainingSteps": 1, "completed": false,
  "segments": [{"step": 1, "row": 0, "col": 1, "seconds": 12, "verdict": "on_target"}],
  "createdAt": "…"
}
```

- `targetSeconds` 为创建时落库的单段目标；未设定（旧客户端/历史数据）为 `null`。
- 设定了目标时，每段 `verdict` 为 `"on_target"`（秒数 ≤ 目标，达标）或
  `"overtime"`（秒数 > 目标，超时），`verdictSummary` 汇总两类段数与对应坐标；
  未设定目标时所有 `verdict` 与 `verdictSummary` 均为 `null`，
  不出现分段判定或汇总，响应其余部分与旧契约一致。

### `POST /api/walk-trials/{id}/undo`（撤回最后一次推进）

现场输错某段秒数时撤回最后一次推进，无需请求体（空体或 `{}` 均可，
多余字段一律拒绝）：

- 在 `BEGIN IMMEDIATE` 事务内删除最后一条逐段记录、检查点回退一格，
  并从**剩余落库分段**重新生成累计时间、完成状态与目标判定汇总；
- 撤回已完成实测的末段后，记录恢复为进行中（`completed=false`、
  `totalSeconds=null`），`nextCoordinate` 重新指向原出口格，
  可按正确秒数继续推进并再次锁定新的总耗时；
- 成功 `200` 返回与创建/推进**相同的完整进度结构**；
- 尚无已确认分段（检查点仍在起点）时返回 422 且定位 `checkpoint` 字段，
  实测编号不存在时定位 `trialId` 字段，**数据不发生变化**。

以下情况返回与核验接口一致的 422 `detail` 字段级错误，且**数据不发生变化**：

| 情况 | 错误 `field` |
| ---- | ------------ |
| `seconds` 不是 1–3600 的整数（含 `3.0`、布尔、字符串、越界、缺失、多余字段） | `seconds` / 多余字段名 |
| `targetSeconds` 不是 1–3600 的整数（含显式 `null`、布尔、字符串、整值小数、越界） | `targetSeconds` |
| 实测编号不存在 | `trialId` |
| 已完成（到达出口）后继续推进 | `completed` |
| 撤回时尚无已确认分段 | `checkpoint` |
| 撤回请求携带多余字段 | 多余字段名 |
| 创建路线不足两格 / 非四方向相邻 | `path` / `path.<索引>` |

## 四、前端行为约定（核验员视角）

1. 选择工具（① 起点 / ② 出口 / ③ 阻挡 / ④ 费力 / 橡皮）后点击格放置；
   起点、出口各只有一个，再次放置即移动；阻挡不能压在起终点上，费力格
   不能压在起点、出口或阻挡格上；橡皮可擦除任意标记。
2. 点「核验最短疏散路线」后：
   - **成功**：蓝色绘制累计通行代价最低的唯一路线（琥珀描边标出路线经过的
     费力格），结果面板显示**步数、米数、通行代价**，可展开有序坐标；
   - **不可达**：琥珀色面板明确显示“不可达”与真实已探索格数，
     灰色标出实际探索范围，画布上没有任何路线；
   - **请求失败**：红色面板按字段列出可操作的中文错误（费力格问题定位到
     `difficultCells.<索引>` 并高亮对应格）；
   - **网络失败**：保持原有“无法连接核验服务”的提示行为。
3. 任何一次对平面的编辑（含改尺寸、放格、擦除）都会立即作废上一次结果，
   画布不残留旧轨迹。
4. 核验**通过**后，结果面板内出现独立的“通行实测”模块：
   - 发起前可选填**单段目标秒数**（1–3600 的整数，留空则不判定）；
     点「发起通行实测」即把当前路线（与目标值）作为不可变快照提交；
     之后逐格输入到达下一格的秒数（1–3600 的整数）并确认；
   - 面板持续显示**下一坐标、累计时间、逐段明细与完成进度条**，
     到达出口后显示并锁定**总耗时**，不再展示推进控件；
   - 进行中与已完成状态都显示「撤回上一段」入口：撤回最后一次推进后
     面板按响应重新展示下一坐标与秒数输入框，可按正确秒数继续；
     请求期间按钮禁用、禁止重复操作；尚无已确认段或编号不存在时，
     字段级反馈（`checkpoint` / `trialId`）留在面板内，
     原路线与当前输入都保留；
   - 设定了目标的实测：每段即时标记**超时**（秒数 > 目标）或**达标**，
     面板同步汇总两类段数与对应坐标，逐段明细中也带判定标记；
   - 秒数非法、目标值非法、编号不存在、完成后推进等反馈都以字段级错误
     形式**留在实测面板内**，不会清除或改动上方已核验通过的原路线；
     目标值被拒时用户填写值保留，便于修正后重试；
   - 未发起实测时页面与旧版完全一致，既有核验/费力格选路行为不受影响。
