# FastAPI 交易订单与风控系统设计

## 1. 项目定位

这是一个用于学习后端工程和交易业务的**模拟交易系统**，不连接真实券商或 MT5，不处理真实资金。

第一版的目标不是覆盖所有交易场景，而是跑通一条可测试的核心链路：

```text
创建模拟账户
  -> 提交订单
  -> 参数校验
  -> 风控检查
  -> 接受或拒绝订单
  -> 模拟成交
  -> 生成持仓
  -> 更新行情
  -> 计算浮动盈亏
  -> 平仓并记录已实现盈亏
```

## 2. 第一版范围

### 要实现

- 模拟账户的创建和查询；
- BUY、SELL 市价订单；
- Pydantic 请求参数校验；
- 账户级风控规则；
- 订单状态机；
- 模拟成交；
- 持仓及简化盈亏计算；
- 统一业务异常；
- Swagger/OpenAPI 文档；
- pytest 接口测试和业务单元测试；
- 第一阶段使用内存仓储，第二阶段替换为数据库。

### 暂不实现

- 真实券商、交易所或 MT5 接入；
- 限价单、止损单、部分成交；
- 多币种换算；
- 杠杆、保证金、点值和隔夜利息的完整模型；
- JWT、Redis、消息队列和微服务；
- 前端网页。

这些能力以后按阶段加入，避免一次引入太多变量。

## 3. 核心领域模型

### Account（账户）

| 字段 | 类型 | 含义 |
|---|---|---|
| id | UUID | 账户唯一标识 |
| name | str | 账户名称 |
| status | ACTIVE / DISABLED | 账户状态 |
| balance | Decimal | 已结算余额 |
| realized_pnl | Decimal | 累计已实现盈亏 |
| created_at | datetime | 创建时间 |

### Order（订单）

| 字段 | 类型 | 含义 |
|---|---|---|
| id | UUID | 订单唯一标识 |
| account_id | UUID | 所属账户 |
| symbol | str | 交易品种，例如 XAUUSD |
| side | BUY / SELL | 买卖方向 |
| volume | Decimal | 下单数量或手数 |
| requested_price | Decimal | 模拟请求价格 |
| status | OrderStatus | 订单状态 |
| reject_reason | str 或 None | 风控拒绝原因 |
| filled_price | Decimal 或 None | 实际模拟成交价 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 最后更新时间 |

### Position（持仓）

| 字段 | 类型 | 含义 |
|---|---|---|
| id | UUID | 持仓唯一标识 |
| account_id | UUID | 所属账户 |
| opening_order_id | UUID | 对应的开仓订单 |
| symbol | str | 交易品种 |
| side | BUY / SELL | 持仓方向 |
| volume | Decimal | 持仓数量 |
| open_price | Decimal | 开仓价 |
| status | OPEN / CLOSED | 持仓状态 |
| close_price | Decimal 或 None | 平仓价 |
| realized_pnl | Decimal 或 None | 平仓后已实现盈亏 |
| opened_at | datetime | 开仓时间 |
| closed_at | datetime 或 None | 平仓时间 |

`current_price` 和 `unrealized_pnl` 是查询持仓时，根据最新 `MarketQuote` 计算出的响应字段，不在每条持仓中重复保存。

### RiskRule（风控规则）

第一版每个账户拥有一组规则：

| 字段 | 示例 | 含义 |
|---|---:|---|
| max_order_volume | 10 | 单笔最大数量 |
| max_order_notional | 100000 | 单笔最大名义金额 |
| max_open_positions | 5 | 最大未平仓持仓数 |
| allowed_symbols | [XAUUSD, EURUSD] | 允许交易的品种 |
| daily_loss_limit | 1000 | 当日最大已实现亏损 |

### RiskDecision（风控决定）

每次下单都保存一次风控结果，而不是只在订单中保存最终状态：

| 字段 | 含义 |
|---|---|
| id | 决定唯一标识 |
| order_id | 对应订单 |
| passed | 是否通过 |
| failed_rule | 未通过的规则代码 |
| reason | 可读的拒绝原因 |
| evaluated_at | 检查时间 |

这能回答“某个订单为什么在当时被拒绝”，便于审计和排障。

## 4. 状态机

订单和持仓必须分开管理。

### 订单状态

```text
PENDING_RISK
  -> ACCEPTED
  -> REJECTED

ACCEPTED
  -> FILLED
  -> CANCELLED
```

允许的转换：

```python
ALLOWED_ORDER_TRANSITIONS = {
    "PENDING_RISK": {"ACCEPTED", "REJECTED"},
    "ACCEPTED": {"FILLED", "CANCELLED"},
    "REJECTED": set(),
    "FILLED": set(),
    "CANCELLED": set(),
}
```

### 持仓状态

```text
OPEN -> CLOSED
```

`FILLED` 是订单的终态。开仓订单成交后创建 `OPEN` 持仓；以后关闭的是持仓，不是把订单改成 `CLOSED`。

## 5. 风控处理顺序

提交订单后按固定顺序检查：

1. 账户是否存在；
2. 账户是否为 `ACTIVE`；
3. 品种是否在允许列表；
4. `volume` 是否超过账户规则；
5. `volume * requested_price` 是否超过名义金额限制；
6. 当前未平仓持仓数是否超过限制；
7. 当日已实现亏损是否触发限额。

Pydantic 和业务服务的职责要分开：

| 校验 | 负责位置 |
|---|---|
| symbol 非空、长度限制 | Pydantic schema |
| side 只能是 BUY 或 SELL | Enum + Pydantic |
| volume 大于 0 | Pydantic schema |
| requested_price 大于 0 | Pydantic schema |
| 账户是否存在或禁用 | OrderService / RiskService |
| 是否允许该 symbol | RiskService |
| 是否超过账户个性化限额 | RiskService |
| 状态能否转换 | 领域状态机 |

## 6. REST API 设计

统一前缀：`/api/v1`

### 账户

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/accounts` | 创建模拟账户 |
| GET | `/accounts/{account_id}` | 查询账户 |
| PATCH | `/accounts/{account_id}` | 启用或禁用账户 |

创建账户请求：

```json
{
  "name": "demo-account",
  "initial_balance": "100000.00"
}
```

### 风控规则

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/accounts/{account_id}/risk-rules` | 查询账户规则 |
| PUT | `/accounts/{account_id}/risk-rules` | 完整更新账户规则 |

### 订单

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/accounts/{account_id}/orders` | 提交订单并执行风控 |
| GET | `/orders/{order_id}` | 查询单个订单 |
| GET | `/accounts/{account_id}/orders` | 查询订单列表 |
| POST | `/orders/{order_id}/cancel` | 撤销已接受但未成交的订单 |
| POST | `/orders/{order_id}/fill` | 模拟撮合成交，仅开发环境使用 |
| GET | `/orders/{order_id}/risk-decision` | 查询风控决定 |

创建订单请求：

```json
{
  "symbol": "XAUUSD",
  "side": "BUY",
  "volume": "0.10",
  "requested_price": "2400.50"
}
```

创建成功并通过风控：

```json
{
  "id": "7b4c...",
  "account_id": "65f1...",
  "symbol": "XAUUSD",
  "side": "BUY",
  "volume": "0.10",
  "requested_price": "2400.50",
  "status": "ACCEPTED",
  "reject_reason": null
}
```

数据格式合法但风控未通过时，仍然创建订单审计记录，返回 `201 Created`，订单状态为 `REJECTED`。客户端不能只看 HTTP 状态码，还必须查看订单状态。

### 持仓

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/accounts/{account_id}/positions` | 查询持仓，可用 status 过滤 |
| GET | `/positions/{position_id}` | 查询单个持仓 |
| POST | `/positions/{position_id}/close` | 模拟平仓 |

### 模拟行情

| 方法 | 路径 | 用途 |
|---|---|---|
| PUT | `/market/quotes/{symbol}` | 新增或替换品种的最新模拟行情 |
| GET | `/market/quotes/{symbol}` | 查询品种的最新模拟行情 |

更新 XAUUSD 模拟行情请求：

```json
{
  "price": "2410.50"
}
```

## 7. HTTP 状态码和错误格式

| 状态码 | 使用场景 |
|---|---|
| 200 | 查询、修改、业务动作成功 |
| 201 | 账户、订单等资源创建成功 |
| 404 | 账户、订单或持仓不存在 |
| 409 | 非法状态转换，例如取消已成交订单 |
| 422 | 请求字段类型、枚举、长度或数值范围错误 |
| 500 | 未预料的服务器错误，不向客户端暴露堆栈 |

统一业务错误：

```json
{
  "error": {
    "code": "INVALID_ORDER_TRANSITION",
    "message": "FILLED 订单不能被取消",
    "details": {
      "order_id": "7b4c...",
      "current_status": "FILLED"
    }
  }
}
```

## 8. 盈亏模型

第一版使用简化公式，并明确它不是完整外汇或期货盈亏算法：

```text
BUY  浮动盈亏 = (current_price - open_price) * volume
SELL 浮动盈亏 = (open_price - current_price) * volume
```

平仓时：

```text
position.realized_pnl = 最后一次计算出的盈亏
account.balance += position.realized_pnl
position.status = CLOSED
```

金额、价格和数量在领域层使用 `Decimal`，避免二进制浮点误差；API JSON 中可用字符串表达精确十进制数。

## 9. 推荐代码结构

```text
app/
├── main.py
├── api/
│   ├── router.py
│   └── v1/
│       ├── accounts.py
│       ├── orders.py
│       ├── positions.py
│       └── risk_rules.py
├── schemas/
│   ├── account.py
│   ├── order.py
│   ├── position.py
│   └── risk.py
├── domain/
│   ├── entities.py
│   ├── enums.py
│   └── state_machine.py
├── services/
│   ├── account_service.py
│   ├── order_service.py
│   ├── position_service.py
│   └── risk_service.py
├── repositories/
│   ├── interfaces.py
│   └── memory.py
├── core/
│   ├── config.py
│   ├── errors.py
│   └── exception_handlers.py
└── dependencies.py

tests/
├── unit/
│   ├── test_order_state_machine.py
│   ├── test_risk_service.py
│   └── test_pnl.py
├── api/
│   ├── test_accounts.py
│   ├── test_orders.py
│   └── test_positions.py
└── conftest.py
```

职责边界：

```text
api          接收 HTTP 请求、调用服务、返回响应
schemas      API 输入输出格式及字段校验
domain       与框架无关的实体、枚举和状态规则
services     用例编排和业务规则
repositories 数据读写抽象
core         配置、异常和通用基础能力
```

路由函数不直接操作全局字典，也不直接计算风控或盈亏。

## 10. 一次下单的内部调用链

```text
POST /api/v1/accounts/{account_id}/orders
  -> FastAPI/Pydantic 校验请求格式
  -> OrderService.create_order()
  -> AccountRepository.get()
  -> OrderRepository.add(PENDING_RISK)
  -> RiskService.evaluate()
  -> RiskDecisionRepository.add()
  -> Order 状态转为 ACCEPTED 或 REJECTED
  -> OrderRepository.save()
  -> 返回 OrderResponse
```

以后接数据库时，上述写操作需要放在同一个事务边界内，避免只保存了订单却没有保存风控决定。

## 11. 最低测试清单

### 参数校验

- symbol 为空时返回 422；
- side 不是 BUY/SELL 时返回 422；
- volume 为 0、负数或超过字段硬上限时返回 422；
- requested_price 小于等于 0 时返回 422。

### 风控

- 禁用账户的订单被拒绝；
- 不允许的品种被拒绝；
- 超过账户单笔数量限制时被拒绝；
- 超过名义金额限制时被拒绝；
- 达到最大持仓数时被拒绝；
- 触发当日亏损限额时被拒绝；
- 每次结果均保存 RiskDecision。

### 状态机

- ACCEPTED 可以变为 FILLED；
- ACCEPTED 可以变为 CANCELLED；
- FILLED 不能取消；
- REJECTED 不能成交；
- 非法转换返回 409。

### 持仓和盈亏

- BUY 和 SELL 的盈亏方向正确；
- 订单只生成一次持仓；
- 平仓后余额正确更新；
- CLOSED 持仓不能再次平仓。

## 12. 开发里程碑

### M1：最小可运行 API

- 建立项目和依赖；
- `GET /health`；
- 创建账户、查询账户；
- 用内存仓储保存数据；
- 完成基础接口测试。

### M2：订单与参数校验

- 创建和查询订单；
- Enum、Field 和响应模型；
- 统一 404、409 错误。

### M3：风控与状态机

- RiskRule、RiskDecision；
- 风控服务；
- 接受、拒绝、取消和模拟成交；
- 单元测试覆盖全部转换。

### M4：持仓与盈亏

- 成交生成持仓；
- 更新模拟行情；
- 浮动盈亏和平仓。

### M5：数据库化

- 引入 MySQL 或 PostgreSQL；
- SQLAlchemy 2.x 和迁移工具；
- 事务、唯一约束和并发保护；
- 保留仓储接口，替换内存实现。

### M6：工程能力

- JWT 和账户归属权限；
- 结构化日志和 request_id；
- Docker Compose；
- CI 测试；
- 幂等键，防止重复下单；
- Redis 和异步任务只在出现明确需求后加入。

## 13. 第一轮验收标准

M1 到 M4 完成后，应该可以用 Swagger 完整演示：

1. 创建一个余额为 100000 的账户；
2. 设置只允许 XAUUSD、最大手数 1；
3. 提交 0.1 手订单并通过风控；
4. 提交 2 手订单并看到 `REJECTED` 及原因；
5. 将第一个订单模拟成交并生成持仓；
6. 更新行情并看到浮动盈亏变化；
7. 平仓并看到余额和已实现盈亏变化；
8. 尝试再次取消或平仓，得到 409；
9. 自动化测试覆盖上述成功和失败路径。
