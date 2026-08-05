# FastAPI 模拟交易订单与风控系统

这是一个用于学习的内存版模拟交易 API，不连接真实券商、MT5 或真实资金。

## 运行环境

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic 2
- pytest

## 安装

在项目目录执行：

```powershell
python -m pip install -e ".[dev]"
```

## 启动

```powershell
python -m uvicorn app.main:app --reload
```

打开：

- Swagger UI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

## 运行测试

```powershell
python -m pytest
```

## 推荐演示顺序

1. `POST /api/v1/accounts` 创建账户；
2. `PUT /api/v1/accounts/{account_id}/risk-rules` 设置风控；
3. `PUT /api/v1/market/quotes/XAUUSD` 设置模拟行情；
4. `POST /api/v1/accounts/{account_id}/orders` 提交订单；
5. `POST /api/v1/orders/{order_id}/fill` 模拟成交；
6. 更新 XAUUSD 行情；
7. `GET /api/v1/positions/{position_id}` 查看浮动盈亏；
8. `POST /api/v1/positions/{position_id}/close` 平仓；
9. 再次查询账户，观察余额和已实现盈亏。

数据只保存在进程内存中。服务器重启后，账户、订单和持仓都会清空。

完整设计说明见 [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)。

