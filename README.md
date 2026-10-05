# FastAPI 交易研究与风控系统

目前可从本机已登录的 MT5 终端只读获取真实 bid/ask Tick 和合约规格。
订单、持仓、成交与账户仍是内存模拟版；**没有实现真实下单**。
默认启动采用 MT5 行情模式，并禁用原模拟报价和模拟订单/成交接口，避免把行情误记成券商成交。

## 运行环境

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic 2
- pytest
- Windows 64 位 + MetaTrader 5 桌面终端（使用 MT5 行情时）

## 安装

项目使用 `uv` 管理依赖。在项目目录执行：

```powershell
uv sync --extra dev --extra mt5
```

本机 `.venv` 已安装官方 `MetaTrader5` Python 包。若不使用 `uv`，也可在虚拟环境运行
`python -m pip install -e ".[dev,mt5]"`。MT5 包只提供 Windows 版本；不需要额外购买 Python API，
但实时价格和交易权限取决于你登录的券商账户及其数据服务。

## 启动

```powershell
$env:MT5_TERMINAL_PATH = 'C:\Program Files\DLS Markets MetaTrader 5 Terminal\terminal64.exe'
uv run --extra mt5 python -m uvicorn app.main:app --reload
```

`MT5_TERMINAL_PATH` 可不设置，此时官方包尝试自动寻找终端；有多个终端时建议明确指定。
终端须保持运行并已连接券商服务器。若券商品种带后缀，可设置例如
`$env:MT5_SYMBOL_MAP = '{"XAUUSD":"XAUUSD.m"}'`。默认内部代码与券商代码同名。

打开 `GET http://127.0.0.1:8000/api/v1/market/ticks/XAUUSD` 可读取最新 Tick：
`bid` 为卖出报价、`ask` 为买入报价、`spread` 为价差，`event_time` 是 MT5 数据时间，
`received_at` 是本机接收时间。`source_time_delta_seconds` 是 MT5 时间减本机接收时间；
终端显示时区不同是正常的，但若 API 原始时间与本机时间基准无法直接比较，
`is_stale` 返回 `null`，**不是**“报价新鲜”。可比较时，超过 30 秒返回 `true`；
阈值可用 `MT5_MAX_TICK_AGE_SECONDS` 调整。不要按固定澳洲时差自行改写历史时间，
夏令时与券商服务器时区需单独确认。读取合约规格使用
`GET /api/v1/market/instruments/XAUUSD`。两个 GET 都不会下单。

正常 MT5 模式启动后，后台采集器每秒轮询 `XAUUSD`，去重后写入
`data/mt5_ticks.sqlite3`。它保留原始 `source_time_msc`、按 UTC 解释的
`event_time`、本机 `received_at`、bid/ask 和券商代码；重启后重复读取的同一
`(品种, 券商代码, 原始毫秒时间, bid, ask)` 不会重复入库。

查看采集状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/market/collector/status |
  ConvertTo-Json -Depth 5
```

`RUNNING` 表示本轮有新 Tick，`IDLE` 表示终端可读但本轮没有新报价，
`RETRYING` 表示连接/读取/落盘失败并在退避重试。`last_error_code`、
`last_success_at`、`persisted_ticks` 可帮助排障。`SOURCE_AHEAD_UNVERIFIED`
只表示采集时观察到 MT5 时间领先本机，**并未确认券商的正式时区或夏令时规则**；
不会自动减去 3 小时。需向券商确认服务器时间规则，再为历史回测制定时间归一化策略。

可配置 `$env:MT5_POLL_INTERVAL_SECONDS='1.0'`、
`$env:MT5_COLLECTOR_SYMBOL='XAUUSD'`、`$env:MT5_TICK_DB_PATH='D:\data\mt5_ticks.sqlite3'`。
`$env:MT5_COLLECTOR_ENABLED='0'` 可关闭后台采集；通常不要开启多个 Uvicorn worker，
当前版本没有跨进程采集租约。`GET /market/ticks/{symbol}` 仍是直接读取终端；
采集器尚未接 EventBus/策略，也不会发单。轮询最新 Tick **不能保证逐笔无缺口**，
后续需要按游标补采历史 Tick 或接 EA 推送。

打开：

- Swagger UI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

## 运行测试

```powershell
python -m pytest
```

## 旧模拟交易演示

只有显式设置 `$env:MARKET_SOURCE = 'sim'` 并重启服务后，才能使用下面的手动行情
与模拟订单接口。切回 MT5 模式请删除此环境变量或设为 `mt5`。

1. `POST /api/v1/accounts` 创建账户；
2. `PUT /api/v1/accounts/{account_id}/risk-rules` 设置风控；
3. `PUT /api/v1/market/quotes/XAUUSD` 设置模拟行情；
4. `POST /api/v1/accounts/{account_id}/orders` 提交订单；
5. `POST /api/v1/orders/{order_id}/fill` 模拟成交；
6. 更新 XAUUSD 行情；
7. `GET /api/v1/positions/{position_id}` 查看浮动盈亏；
8. `POST /api/v1/positions/{position_id}/close` 平仓；
9. 再次查询账户，观察余额和已实现盈亏。

账户、订单和持仓只保存在进程内存中，服务器重启后会清空；MT5 采样 Tick
单独保存在 SQLite 中，但目前不是完整、可回放的 Event Journal。

完整设计说明见 [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)。

事件驱动改造的第一步（领域对象、事件、与现有模块的对应关系）见
[DOMAIN_MODEL_V1.md](DOMAIN_MODEL_V1.md)。运行可打印事件链的示例：

```powershell
python -m examples.domain_flow
```

