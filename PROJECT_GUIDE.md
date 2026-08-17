# 项目整体逻辑说明与后续路线

> 本文档面向「刚克隆下来、想快速读懂代码」的读者，说明本项目由哪些模块组成、每个模块干什么、请求如何流转，并给出通往 MT5 黄金量化交易的下一阶段建议。
>
> 配套文档：[README.md](README.md)（运行与演示）、[SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)（第一版设计规格）。

---

## 1. 一句话定位

这是一个**不接真实券商、不碰真实资金**的学习型「模拟交易订单 + 风控系统」。它先跑通一条最核心的链路：

```text
创建账户 → 提交订单 → 参数校验 → 风控检查 → 接受/拒绝 → 模拟成交 → 生成持仓
        → 更新行情 → 计算浮动盈亏 → 平仓结算 → 记录已实现盈亏
```

它同时是一块**面向未来的地基**：代码在「行情来源」和「数据存储」两个位置留了清晰的替换缝，之后可以平滑地把手动模拟行情换成 MT5 实时行情、把内存仓库换成数据库。

---

## 2. 目录结构总览

```text
python_explore/
├── app/
│   ├── main.py                    # 应用入口：组装 app、注册异常处理、挂载路由
│   ├── dependencies.py            # FastAPI 依赖注入：把 db 和服务接线
│   ├── api/
│   │   ├── router.py              # 汇总 v1 路由，统一 /api/v1 前缀
│   │   └── v1/
│   │       ├── accounts.py        # 账户 + 风控规则接口
│   │       ├── orders.py          # 订单接口（下单/查询/撤单/成交/风控结果）
│   │       ├── market.py          # 模拟行情接口
│   │       └── positions.py       # 持仓接口（查询/平仓）
│   ├── schemas/                   # HTTP 请求/响应模型（Pydantic 校验）
│   │   ├── account.py  market.py  order.py  position.py  risk.py
│   ├── domain/                    # 与框架无关的领域层
│   │   ├── entities.py            # 领域实体（Account/Order/Position 等）
│   │   ├── enums.py               # 状态与方向枚举
│   │   └── state_machine.py       # 订单状态机
│   ├── services/                  # 用例编排与业务规则
│   │   ├── account_service.py     # 账户/风控规则
│   │   ├── order_service.py       # 订单（含风控编排、成交）
│   │   ├── position_service.py    # 持仓（盈亏计算、平仓）
│   │   ├── risk_service.py        # 风控检查
│   │   └── market_service.py      # 行情读写与成交前检查
│   ├── strategy/                  # ★ 策略层：交易决策与执行解耦
│   │   ├── base.py                # Strategy 抽象接口 + Signal 信号
│   │   ├── context.py             # MarketContext 只读市场快照
│   │   ├── ma_cross.py            # 示例策略：双均线金叉/死叉
│   │   └── runner.py              # 调度器：行情 → 策略 → 下单
│   ├── repositories/
│   │   └── memory.py              # 内存仓储（第一版存储实现）
│   └── core/
│       ├── errors.py              # 统一业务异常
│       └── exception_handlers.py  # 异常 → JSON 错误响应
├── tests/
│   ├── conftest.py                # pytest 夹具（隔离的应用与账户）
│   ├── unit/test_business_rules.py    # 状态机 + 盈亏方向
│   ├── api/
│   │   ├── test_orders.py         # 订单失败路径/边界
│   │   └── test_trading_flow.py   # 完整交易链路
│   └── strategy/
│       └── test_strategy_flow.py  # 策略 → 风控 → 成交 链路
├── pyproject.toml                 # 项目元数据与依赖
├── README.md                      # 运行说明
└── SYSTEM_DESIGN.md               # 设计规格
```

---

## 3. 分层架构与职责边界

代码刻意分成了七层，每一层只做自己该做的事：

| 层 | 目录 | 职责 | 不做什么 |
|---|---|---|---|
| **API 层** | `api/` | 接收 HTTP 请求、调用服务、返回响应 | 不直接算风控/盈亏，不直接操作字典 |
| **Schema 层** | `schemas/` | 定义输入输出的格式和字段校验 | 不写业务规则（账户是否禁用等） |
| **领域层** | `domain/` | 实体、枚举、状态转换规则 | 不依赖 FastAPI/Pydantic/数据库 |
| **策略层** | `strategy/` | 交易决策：根据行情/账户/持仓产出买卖信号 | 不直接下单、不绕过风控 |
| **服务层** | `services/` | 用例编排、业务规则、盈亏计算 | 不直接碰 HTTP 细节 |
| **仓储层** | `repositories/` | 数据的读写抽象 | 不实现业务逻辑 |
| **核心层** | `core/` | 统一异常、异常处理器 | 不涉及具体交易业务 |

**依赖方向是单向的**：`api → services → (domain + repositories)`；`strategy` 是与之并列的**决策层**，只依赖 `domain`（实体/枚举），并通过 `StrategyRunner` 调用 `services` 层下单，不反向被 services 依赖。`schemas` 和 `core` 被各层共用。领域层在最底层，不反向依赖上层。

> 关键设计：`schemas`（HTTP 能看到的数据）和 `domain.entities`（系统真正保存的对象）是**两套模型**。比如 `Position` 实体里没有 `current_price` 和 `unrealized_pnl`，这两个字段是查询时按最新行情现算出来的，放到响应模型里返回。

---

## 4. 领域模型（核心概念）

这些是系统真正在内存中保存和处理的对象（定义在 `app/domain/entities.py`）：

| 实体 | 作用 | 关键字段 |
|---|---|---|
| **Account** | 模拟交易账户 | `balance`（已结算余额）、`realized_pnl`（累计已实现盈亏）、`status`（ACTIVE/DISABLED） |
| **RiskRule** | 账户风控阈值 | `max_order_volume`、`max_order_notional`、`max_open_positions`、`allowed_symbols`、`daily_loss_limit` |
| **Order** | 客户交易意图 | `side`（BUY/SELL）、`volume`、`requested_price`（下单参考价）、`status`、`filled_price`（成交价）、`reject_reason` |
| **RiskDecision** | 一次风控的审计结果 | `passed`、`failed_rule`、`reason`（回答「这个订单当时为什么被拒」） |
| **MarketQuote** | 某品种最新模拟行情 | `symbol`、`price` |
| **Execution** | 开仓/平仓成交记录 | `kind`（OPEN/CLOSE）、`price`、关联的 `order_id`/`position_id` |
| **Position** | 成交后形成的持仓 | `side`、`volume`、`open_price`、`status`（OPEN/CLOSED）、`realized_pnl` |

**订单与持仓是分开的两套东西**：`FILLED` 是订单的终态；订单成交后创建 `OPEN` 持仓；之后平仓操作的是持仓，而不是把订单改成 `CLOSED`。

---

## 5. 订单状态机

定义在 `app/domain/state_machine.py`，是所有状态变更的唯一入口：

```text
                    ┌──────────────────────────────┐
                    │         PENDING_RISK         │   ← 新订单的初始状态
                    └──────────┬─────────┬─────────┘
                    通过风控     │         │ 风控拒绝
                        ┌───────▼──┐   ┌──▼────────┐
                        │ ACCEPTED │   │ REJECTED  │  (终态，不再变化)
                        └────┬─────┘   └───────────┘
                  ┌──────────┴──────────┐
            模拟成交 │                    │ 撤单
              ┌─────▼─────┐        ┌─────▼─────┐
              │  FILLED   │        │ CANCELLED │  (都是终态)
              └───────────┘        └───────────┘
```

- `transition_order(order, target)` 会先检查 `ALLOWED_ORDER_TRANSITIONS`，非法转换直接抛 `ConflictError`（HTTP 409）。
- 所有服务改订单状态都必须走这个函数，防止业务代码绕过生命周期规则。

持仓状态机简单得多：`OPEN → CLOSED`，平仓后再平仓会得到 409。

---

## 6. 各模块工作方式

### 6.1 `app/main.py` — 应用入口

用**工厂函数** `create_app(db=None)` 创建 FastAPI 应用：不传参时为当前进程创建一份内存数据库，测试则传入全新数据库保证隔离。启动后：

1. 把 `InMemoryDatabase` 挂到 `application.state.db`（所有请求共享这一份数据）；
2. `register_exception_handlers` 注册统一异常处理；
3. `include_router(api_router)` 挂载业务路由；
4. 额外定义 `GET /health`。

### 6.2 `app/dependencies.py` — 依赖注入

用 FastAPI 的 `Depends` 把「数据库 → 服务」接起来。路由函数只声明自己需要哪种服务（如 `OrderServiceDep`），由框架在每次请求时创建服务实例并注入同一个 `db`。这样接口层很薄，测试也容易替换依赖。

### 6.3 `app/repositories/memory.py` — 内存存储

`InMemoryDatabase` 用 7 个字典按资源类型存储数据，并用一个 **`RLock`（可重入锁）** 保护复合读写（FastAPI 同步路由在线程池并发执行）。它没有持久化，程序重启数据全丢。将来接数据库时，替换这一层、保持服务层接口不变即可。

### 6.4 `app/core/` — 异常体系

- `errors.py`：定义 `DomainError` 基类和 `NotFoundError`(404)、`ConflictError`(409) 两个子类，携带 `code`、`message`、`details`。
- `exception_handlers.py`：把 `DomainError` 统一转成 `{"error": {code, message, details}}` 的 JSON 格式。

业务服务里抛异常，由处理器转 HTTP 状态码，服务层不依赖 HTTP。

### 6.5 `app/schemas/` — 输入输出模型

- **输入模型**（`*Create`/`*Update`）负责字段级校验：`symbol` 非空、`side` 只能是 BUY/SELL、`volume > 0`、`requested_price > 0`、Decimal 精度上限等。这些用 `Field(gt=0, max_digits=18, decimal_places=6)` 和 `field_validator` 实现。
- **输出模型**（`*Response`）用 `ConfigDict(from_attributes=True)` 直接从领域实体读取字段。
- 一个易踩的点：`order.py` 里 `FillOrderResponse` 引用了 `PositionResponse`，为避免循环导入，把 import 放到了文件末尾。

### 6.6 服务层各模块

#### `AccountService`（account_service.py）
账户与风控规则的 CRUD。创建账户时**同时**写入一份默认 `RiskRule`（放同一临界区）。提供 `get_risk_rule` / `update_risk_rule`（完整替换）。

#### `RiskService`（risk_service.py）
`evaluate()` 按**固定顺序**检查，命中第一条失败规则立即返回拒绝决定（**不抛异常**，因为风控拒绝是正常业务结果）：

1. 账户状态是否 `ACTIVE` → 否则 `ACCOUNT_DISABLED`
2. 品种是否在 `allowed_symbols` → 否则 `SYMBOL_NOT_ALLOWED`
3. `volume` 是否超 `max_order_volume` → `MAX_ORDER_VOLUME_EXCEEDED`
4. `volume * requested_price` 是否超名义金额 → `MAX_ORDER_NOTIONAL_EXCEEDED`
5. 未平仓持仓数是否达上限 → `MAX_OPEN_POSITIONS_REACHED`
6. 当日已实现亏损是否达限 → `DAILY_LOSS_LIMIT_REACHED`

每次评估都生成 `RiskDecision` 存下来，供审计接口查询。

#### `OrderService`（order_service.py）
订单用例的总协调者，组合 Account/Market/Risk 三个子服务：

- `create()`：**先**把订单以 `PENDING_RISK` 存库 → 执行风控 → 根据结果转成 `ACCEPTED` 或 `REJECTED`（拒绝订单也保存，`reject_reason` 记录原因）。
- `cancel()`：状态机只允许 `ACCEPTED → CANCELLED`。
- `fill()`：模拟成交——用**最新行情**价（不是下单参考价）成交，创建 `Execution`(OPEN) 和 `Position`，并把订单转 `FILLED`。内含两层幂等保护：状态机限制 + 检查「一个开仓订单最多对应一条持仓」。
- `get_risk_decision()`：读取订单当时的风控审计结果。

#### `PositionService`（position_service.py）
持仓查询、盈亏计算、平仓：

- `calculate_pnl()`：第一版简化公式
  - BUY：`(current_price - open_price) * volume`
  - SELL：`(open_price - current_price) * volume`
- `close()`：用最新行情平仓，写入 `Execution`(CLOSE)，持仓转 `CLOSED`，把 `realized_pnl` 结算进账户余额和累计盈亏。
- `to_view()`：把实体转成响应视图——OPEN 持仓按最新行情现算 `current_price`/`unrealized_pnl`，CLOSED 持仓浮动盈亏归零。

#### `MarketDataService`（market_service.py）
模拟行情的读写。`require_quote_for_execution()` 是成交/平仓前检查：报价缺失时把 404 转成 409（因为对成交动作来说，缺行情是「当前业务条件不满足」）。

### 6.7 API 层各路由（`app/api/v1/`）

统一前缀 `/api/v1`：

| 资源 | 端点 | 说明 |
|---|---|---|
| 账户 | `POST /accounts` | 创建账户（自动带默认风控规则） |
| | `GET /accounts/{id}` | 查询账户 |
| | `PATCH /accounts/{id}` | 启用/禁用 |
| 风控规则 | `GET/PUT /accounts/{id}/risk-rules` | 查询 / 完整替换规则 |
| 订单 | `POST /accounts/{id}/orders` | 下单并同步风控，返回 ACCEPTED/REJECTED |
| | `GET /orders/{id}`、`GET /accounts/{id}/orders` | 查单 / 列表（可 status 过滤） |
| | `POST /orders/{id}/cancel`、`POST /orders/{id}/fill` | 撤单 / 模拟成交 |
| | `GET /orders/{id}/risk-decision` | 查风控审计结果 |
| 持仓 | `GET /accounts/{id}/positions`、`GET /positions/{id}` | 查持仓 |
| | `POST /positions/{id}/close` | 平仓结算 |
| 行情 | `PUT/GET /market/quotes/{symbol}` | 手动写 / 查模拟行情 |

> 一个重要约定：数据格式合法但**风控拒绝**时，仍返回 `201 Created`，只是订单 `status=REJECTED`。客户端不能只看 HTTP 状态码，必须看订单状态。

### 6.8 策略层（`app/strategy/`）

这是为「MT5 黄金量化」预留的**决策层**，与 `services/` 并列。它回答你之前的疑问：**下单策略写在哪里**——就写在这一层，每个策略是一个独立类，只负责产出买卖信号。

| 文件 | 作用 |
|---|---|
| `base.py` | `Strategy` 抽象基类 + `Signal` 信号（`side`/`symbol`/`volume`/`reason`）。所有策略实现 `on_tick(context) -> Signal \| None` |
| `context.py` | `MarketContext` 只读快照：最新报价、账户、未平仓持仓、风控规则。用 `frozen=True` 提醒策略「只读不写」 |
| `ma_cross.py` | 示例策略 `MovingAverageCrossoverStrategy`：快线上穿慢线（金叉）→ BUY，下穿（死叉）→ SELL |
| `runner.py` | `StrategyRunner` 调度器：`on_quote()` 每收到一条报价 → 更新行情 → 组装上下文 → 调策略 → 有信号就复用 `OrderService.create()` 下单 |

**关键设计**：

1. **策略只做决策，不做执行**：策略返回 `Signal`，不碰订单/持仓/数据库；下单走 `OrderService`。
2. **策略绕不过风控**：信号进的是 `OrderService.create()`，后面自动过 `RiskService` 的 6 条规则，不通过就是 `REJECTED` + 审计记录。
3. **同一接口用于回测**：`on_tick(context)` 的输入是「一条行情 + 账户快照」，回测时把实时 tick 换成历史 tick，策略代码完全复用。

---

## 7. 一次完整下单的调用链

以 `POST /api/v1/accounts/{id}/orders` 为例：

```text
HTTP 请求
  → FastAPI/Pydantic 校验格式（schemas.OrderCreate）        ← 字段级错误返回 422
  → 依赖注入创建 OrderService（共享同一个 db）
  → OrderService.create()
       → AccountService.get()             # 账户不存在 → 404
       → AccountService.get_risk_rule()
       → 写入 Order（状态 PENDING_RISK）
       → RiskService.evaluate()           # 返回 RiskDecision（通过/拒绝）
       → 写入 RiskDecision
       → transition_order()               # PENDING_RISK → ACCEPTED / REJECTED
  → 返回 OrderResponse（201）
```

成交与平仓：

```text
POST /orders/{id}/fill
  → OrderService.fill()
       → 状态机校验（仅 ACCEPTED 可成交）
       → 幂等检查（该订单是否已生成持仓）
       → MarketDataService.require_quote_for_execution()   # 无行情 → 409
       → 创建 Execution(OPEN) + Position(OPEN)
       → 订单转 FILLED，filled_price = 最新行情价
  → 返回 {order, position}

POST /positions/{id}/close
  → PositionService.close()
       → 校验状态（仅 OPEN 可平）
       → 取最新行情 → calculate_pnl()
       → 创建 Execution(CLOSE)
       → 持仓转 CLOSED，记录 close_price/realized_pnl
       → 账户 balance += realized_pnl
  → 返回持仓视图
```

策略驱动的调用链（将来接 MT5 后的主路径）：

```text
MT5 实时行情(tick) ──► MarketDataService.update_quote()
                          │
                          ▼
                   StrategyRunner.on_quote()
                          │ 组装 MarketContext（行情/账户/持仓/风控规则）
                          ▼
                   Strategy.on_tick() ──► Signal(BUY/SELL, volume, reason)
                          │ 无信号则返回 None
                          ▼
                   OrderService.create()          ← 复用现有下单管道
                          │
              RiskService 检查 → ACCEPTED / REJECTED(+审计)
                          │
                   fill() → MT5 order_send（真实下单，阶段 D）
```

---

## 8. 测试如何组织

`tests/` 用 pytest，`conftest.py` 提供了两个关键夹具：

- `client`：每个测试都用**全新的 `InMemoryDatabase`** 创建独立 app，保证用例互不影响；
- `account_id`：预先创建一个默认账户并返回它的 id。

三类测试：

1. **单元测试**（`unit/test_business_rules.py`）：直接验证状态机非法转换、以及 BUY/SELL × 涨/跌 四种盈亏方向。
2. **订单边界测试**（`api/test_orders.py`）：422 参数校验、撤单后不能成交（409）、无行情不能成交、禁用账户订单被拒且留审计、未知订单 404。
3. **完整链路测试**（`api/test_trading_flow.py`）：从建账户 → 收紧风控 → 下单通过/拒绝 → 成交 → 行情变动算浮动盈亏 → 平仓结算 → 余额更新 → 重复操作返回 409，覆盖 BUY 和 SELL 两条路径。
4. **策略链路测试**（`strategy/test_strategy_flow.py`）：双均线金叉/死叉信号、策略信号 → 下单 → 通过风控 → 成交 → 盈亏的完整链路，以及「策略超限信号被风控拒绝」的边界。

---

## 9. 当前完成度对照设计

设计文档（SYSTEM_DESIGN.md）的里程碑进度：

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M1 最小可运行 API | /health、账户、内存仓储 | ✅ |
| M2 订单与参数校验 | 订单 CRUD、校验、404/409 | ✅ |
| M3 风控与状态机 | 风控规则/决定、状态机、撤单/成交 | ✅ |
| M4 持仓与盈亏 | 成交生成持仓、行情、盈亏、平仓 | ✅ |
| M5 数据库化 | SQLAlchemy + MySQL/PostgreSQL | ⬜ 未开始 |
| M6 工程能力 | JWT、日志、Docker、CI、幂等键 | ⬜ 未开始 |

**第一版（M1–M4）功能已完成**，代码质量扎实、测试覆盖充分。

---

## 10. 下一阶段路线建议（通往 MT5 黄金量化）

当前代码为接 MT5 留了两个关键「替换缝」：**行情来源**（`MarketDataService`）和**数据存储**（`repositories`）。建议按下面顺序推进，每步都能独立验收：

### 阶段 A：先持久化（对应设计 M5）

现在所有数据在内存里，重启即丢，无法积累历史。先做数据库化：

- 引入 **SQLAlchemy 2.x + PostgreSQL**（或 MySQL），用 Alembic 管迁移；
- **保留仓储接口**，新增 `SQLAlchemyRepository` 替换 `memory.py`，服务层几乎不改；
- 把「订单写入 + 风控决定写入」「平仓成交 + 持仓更新 + 余额更新」放进**同一事务**（代码里已用注释标出这些位置）；
- 加唯一约束、并发保护（如乐观锁），防止重复持仓/重复平仓。

> 验收标准：重启服务后账户、订单、持仓、风控审计仍在，交易历史可查询。

### 阶段 B：工程加固（对应设计 M6）

量化系统要能长期稳定运行、可观测、可回放：

- **结构化日志 + request_id**，每次下单/成交/平仓都留可追溯日志；
- **订单幂等键**：客户端带 `idempotency_key`，防止网络重试导致重复下单（真实交易里这是致命的）；
- **JWT + 账户归属**：接口只允许操作自己的账户；
- **Docker Compose + CI**：一键起服务、自动跑测试。

> 验收标准：同一幂等键重复提交只产生一笔订单；日志能还原任意一笔订单的完整链路。

### 阶段 C：接入 MT5 行情（黄金量化的第一步关键替换）

这是把「模拟系统」变成「真实系统」的第一刀，**先只接行情、不接下单**（风险最低）：

- 把 `MarketDataService` 的手动 `PUT /market/quotes` 换成 **MT5 行情订阅**（MetaTrader5 Python API 的 `symbol_info_tick` / tick 回调），提供 `bid/ask` 两条价格；
- 新增一个后台任务/线程持续刷新内存里的最新报价，HTTP 写入仅保留给回测/演练；
- 针对 **XAUUSD 黄金**补齐交易语义（这是当前简化模型缺失、但对黄金量化至关重要的部分）：
  - **合约规格**：1 标准手 = 100 盎司，盈亏要乘合约量；
  - **点值 / 报价单位**：黄金报价精确到 0.01，计算 pip、点值；
  - **点差（spread）**：买入用 ask、卖出用 bid，平仓用反向价；
  - **杠杆 / 保证金**：占用保证金、可用保证金、强平线；
  - **隔夜利息（swap）**：持仓过夜成本。

> 验收标准：行情来自真实 MT5；BUY 用 ask 成交、SELL 用 bid 成交；盈亏含合约量与点差。

### 阶段 D：接入 MT5 真实下单（第二步替换）

行情接稳后再碰资金：

- 把 `OrderService.fill()` 的「模拟成交」替换为 **MT5 下单 API**（`order_send`），`fill` 之前的订单/风控逻辑保持不变；
- 成交回报从 MT5 异步回来，需要**状态机新增状态**（如 `SUBMITTED → FILLED/PARTIALLY_FILLED/REJECTED`），补上「部分成交」「滑点」处理；
- 增加**限价单、止损单、止盈单**（设计文档里列为暂不实现的能力，黄金交易几乎必用）；
- 全程**纸面/模拟账户（demo account）**先行，不碰真实资金。

> 验收标准：demo 账户下，下单指令真实到达 MT5，成交回报能正确回写持仓与余额。

### 阶段 E：风控升级 + 策略层

- **策略层骨架已搭好**：`app/strategy/` 已提供 `Strategy` 接口、`MarketContext` 快照、示例双均线策略和 `StrategyRunner`，并带完整链路测试。你可以直接在 `ma_cross.py` 旁边新增自己的策略类。
- **风控增强**：持仓级止损/止盈、最大回撤、保证金占用上限、熔断（kill switch）、单日最大亏损自动停止交易；
- **策略扩展**：把「信号生成」和「执行」进一步解耦——策略只产出买卖信号，交给已建好的订单/风控/执行链路；接入阶段 C 的 MT5 行情后，runner 换成真实 tick 驱动即可。
- **回测框架**：用已积累的历史行情做回测，验证策略在黄金上的表现。

---

## 11. 已知限制与注意点

- **内存存储**：重启丢数据（阶段 A 解决）；
- **简化盈亏**：不含合约大小、点值、点差、杠杆、swap（阶段 C 解决）；
- **对冲式持仓**：每个开仓订单独立成一条持仓，不合并同品种仓位；
- **无认证**：任何客户端都能操作任意账户（阶段 B 解决）；
- **手动行情**：价格靠 `PUT /market/quotes` 手动喂（阶段 C 解决）。
