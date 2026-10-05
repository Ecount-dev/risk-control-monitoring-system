# 第一步：统一领域对象与事件

这一步落实此前路线中的第 1 项：定义 `Instrument、Tick、Bar、Signal、Order、Fill、Position` 及它们对应的事件。目标是让手动 API、策略、未来历史数据播放器和 MT5 Adapter 使用相同的交易语言。现在已额外实现 MT5 **只读**行情 Adapter，但未启动后台交易循环，也没有把 Tick 接到策略或 EventBus。

运行示例：

```powershell
.\.venv\Scripts\python.exe -m examples.domain_flow
.\.venv\Scripts\python.exe -m pytest -q
```

## 看懂这七个对象

| 对象 | 它表达的事实或意图 | 本次代码 | 和旧项目的关系 |
|---|---|---|---|
| `InstrumentId` / `Instrument` | 品种与场所，以及合约规格、价格步长、数量步长 | `app/domain/market.py` | 新增；`XAUUSD@SIM` 与 `XAUUSD@MT5` 是不同品种；规格需要显式配置 |
| `Tick` | 一个时点的 `bid/ask`，附数据源时间和接收时间 | `app/domain/market.py` | 新增；旧 `MarketQuote.price` 只有单价，不把它假装成真实双边报价 |
| `Bar` | 一个时间段已经收盘的 OHLCV K 线 | `app/domain/market.py` | 新增；未收盘 K 线要等下一阶段行情聚合器处理 |
| `Signal` | 策略希望买/卖多少、为什么，附策略身份和信号 ID | `app/domain/signals.py` | 把原 `strategy/base.py` 中的类移到领域层；原导入路径仍可用 |
| `Order` | 风控和执行处理中的订单状态 | `app/domain/entities.py` | 继续使用原订单，添加 `venue/strategy_id/signal_id` 与构造校验；对外 API 字段未变 |
| `Fill` | 一次实际成交，含账户、订单/持仓关联、数量和价格 | `app/domain/entities.py` | 原 `Execution` 成为 `Fill` 的旧名称；开仓和平仓现在创建完整、不可变的成交对象 |
| `Position` | 一个开仓订单形成的独立持仓及其平仓结果 | `app/domain/entities.py` | 继续使用原持仓，添加 `venue/strategy_id` 与构造校验 |

`Decimal`、明确带时区的 UTC 时间、标准化的品种代码、严格正数金额是基础约束。合约的 `contract_size` 和数量单位单独配置：测试和示例中的 `SIM` 规格是虚构数据，不能拿来当 MT5 黄金合约规格。`Instrument.validate_price/validate_volume` 已经提供可调用的检查方法；旧模拟 API 尚未注册合约，也不自动执行这两项检查。

`Signal` 是策略意图，`Order` 是系统接收并处理的订单，`Fill` 是已成交事实，`Position` 是成交带来的仓位。它们不是同一个对象。当前一笔开仓订单仍只有一次完整成交；`Fill` 用独立 ID 为未来的部分成交预留了表达空间，但 OMS 尚未支持部分成交。原平仓接口直接按持仓平仓，没有独立平仓订单，因此平仓 Fill 的 `order_id=None`，只关联 `position_id`；以后进入 OMS 时应补正式平仓订单。

## 事件怎样串起现有流程

每个事件都有 `event_id`（这条事件自身）、`event_time`（业务发生时间）、`recorded_at`（进程记录时间）、`source`、`correlation_id`（一条交易链共享的 ID）、可选 `causation_id`（已知直接上游事件）和 `schema_version`。`to_dict()` 将 UUID、时间、Decimal 转成可 JSON 编码的数据；Decimal 以字符串保存，不丢精度。事件字段和内部载荷不可变；订单、持仓则使用 `OrderSnapshot/PositionSnapshot`，因此后续状态变化不会改写之前的事件。

```text
MarketQuote 更新 ── QuoteUpdated                         （旧模拟行情）
Tick / Bar ──────── TickReceived / BarClosed              （新契约示例）

策略给出 Signal ─── SignalGenerated
创建订单 ────────── OrderCreated(PENDING_RISK)
风控结果 ────────── RiskEvaluated
状态变化 ────────── OrderStateChanged(ACCEPTED/REJECTED)
模拟成交 ────────── FillRecorded(OPEN)
状态变化 ────────── OrderStateChanged(FILLED)
持仓形成 ────────── PositionOpened
模拟平仓 ────────── FillRecorded(CLOSE)
持仓结束 ────────── PositionClosed
余额更新 ────────── AccountSettled
```

撤单会生成 `OrderStateChanged(CANCELLED)`；被风控拒绝的订单会留下 `RiskEvaluated` 和拒绝状态，不会生成成交。运行成功和失败路径的测试见 `tests/strategy/test_domain_event_flow.py`。事件目前写进 `InMemoryDatabase.events`，最多默认保存 10000 条，满后覆盖最旧记录。它是观察和验收工具，**不是可靠 Event Journal**；重启会丢失，不能据此恢复账户或证明审计完整性。

## 原项目具体改了什么

| 原文件 | 本次改动 | 原接口是否还能用 |
|---|---|---|
| `app/strategy/base.py` | `Signal` 改从 `app.domain.signals` 导入 | 能，原导入路径保持 |
| `app/strategy/runner.py` | 策略信号加 ID 和实例归属，先写信号事件，再带关联 ID 下单；检查信号品种与触发行情一致 | 能，`strategy_id` 是可选新增参数 |
| `app/services/order_service.py` | 订单创建、风控、撤单、成交时写标准事件；开仓 Fill 一次填齐关联字段 | 能，HTTP 请求/响应保持 |
| `app/services/position_service.py` | 平仓写成交、持仓和余额事件 | 能，HTTP 请求/响应保持 |
| `app/services/market_service.py` | 写单价 `QuoteUpdated`，不将它伪装为双边 Tick | 能，旧行情接口保持 |
| `app/repositories/memory.py` | 添加有界内存事件记录器 | 能，旧内存字典保持 |
| `app/core/exception_handlers.py` | 领域校验错误统一映射到 HTTP 422 | 能，现有错误响应格式保持 |

### 下阶段哪些文件需要继续拆

这一步只统一语言，没有将整个系统一次性拆成十几个引擎。后续工作的对应关系：

| 目标模块 | 从当前项目迁移的职责 | 现在仍缺少的关键能力 |
|---|---|---|
| `MarketDataAdapter` | 旧 `MarketDataService` 仅用于模拟单价；`MT5MarketDataAdapter` 读取真实 Tick/合约规格；`MarketDataCollector` 后台轮询并去重落 SQLite | 历史 Bar/Tick 补采与播放、券商时间规则确认、完整逐笔保证 |
| `EventBus + Clock` | 现有 Service 直接调用及内存事件记录 | 发布/订阅、事件排序、模拟时间与真实时间切换 |
| `FeatureEngine` | `ma_cross.py` 中的均线队列 | 指标按品种与周期隔离、预热及重启恢复 |
| `StrategyEngine` | `StrategyRunner` | 多策略生命周期、订阅和异常隔离 |
| `PortfolioEngine` | `PositionService`、`AccountService` | 持仓汇总、合约规格、点差/费用、保证金和目标仓位 |
| `RiskEngine` | `RiskService` | 活动订单风险占用、成交前复核、最大敞口/熔断 |
| `OMS` | `OrderService`、`state_machine.py` | 发单/回报/未知状态、部分成交、订单幂等与对账 |
| `ExecutionEngine + MT5Gateway` | 当前手动 `fill()` | 模拟撮合和真实执行采用统一接口；MT5 回报映射 |
| `Event Journal + Persistence` | 当前进程内字典和有界事件记录 | 持久化、事务、快照、版本迁移与重启恢复 |

旧模拟链路仍是 `StrategyRunner.on_quote → MarketDataService → Strategy → OrderService → RiskService → 手动 fill → PositionService`，仅在 `MARKET_SOURCE=sim` 下运行。正常启动的 MT5 链路现在有 `后台 Collector → MT5MarketDataAdapter → MT5 终端 → SQLite Tick 样本`，HTTP 可查询最新报价和采集状态；不会写模拟报价，也不会自动驱动旧策略、发单或生成成交。若 MT5 原始时间与本机接收时间的基准不一致，接口的 `is_stale=null`，不会误称行情已验证新鲜。新的 `Instrument` 尚未进入资金和盈亏公式。下一步应实现 `Clock + EventBus`，再逐步把实时 Tick 接入特征和策略；需要真实执行时另做 OMS/ExecutionGateway 与对账。
