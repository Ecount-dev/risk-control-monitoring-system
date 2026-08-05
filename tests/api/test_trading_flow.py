"""从 HTTP 层验证一条完整模拟交易链路。"""

from decimal import Decimal

from fastapi.testclient import TestClient


def test_complete_buy_order_flow(
    client: TestClient,
    account_id: str,
) -> None:
    """验证 BUY 订单从风控、成交到平仓结算的完整生命周期。"""
    # 1. 收紧账户风控，后面分别验证一笔通过和一笔拒绝的订单。
    risk_response = client.put(
        f"/api/v1/accounts/{account_id}/risk-rules",
        json={
            "max_order_volume": "1.00",
            "max_order_notional": "100000.00",
            "max_open_positions": 5,
            "allowed_symbols": ["XAUUSD"],
            "daily_loss_limit": "1000.00",
        },
    )
    assert risk_response.status_code == 200

    # 2. 成交前必须先提供该品种的模拟行情。
    quote_response = client.put(
        "/api/v1/market/quotes/XAUUSD",
        json={"price": "2401.00"},
    )
    assert quote_response.status_code == 200

    # 3. 0.1 手没有超过限制，订单应当被接受。
    accepted_response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        json={
            "symbol": "xauusd",
            "side": "BUY",
            "volume": "0.10",
            "requested_price": "2400.50",
        },
    )
    assert accepted_response.status_code == 201
    accepted_order = accepted_response.json()
    assert accepted_order["symbol"] == "XAUUSD"
    assert accepted_order["status"] == "ACCEPTED"
    order_id = accepted_order["id"]

    # 4. 2 手超过 max_order_volume=1，订单保留但状态应为 REJECTED。
    rejected_response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        json={
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "2.00",
            "requested_price": "2400.50",
        },
    )
    assert rejected_response.status_code == 201
    rejected_order = rejected_response.json()
    assert rejected_order["status"] == "REJECTED"
    assert "超过限制" in rejected_order["reject_reason"]

    # 5. 风控决定应当准确记录命中的规则代码。
    decision_response = client.get(
        f"/api/v1/orders/{rejected_order['id']}/risk-decision"
    )
    assert decision_response.status_code == 200
    assert decision_response.json()["failed_rule"] == (
        "MAX_ORDER_VOLUME_EXCEEDED"
    )

    # 6. 使用最新价格成交，订单变 FILLED，并生成 OPEN 持仓。
    fill_response = client.post(f"/api/v1/orders/{order_id}/fill")
    assert fill_response.status_code == 200
    fill_result = fill_response.json()
    assert fill_result["order"]["status"] == "FILLED"
    assert Decimal(fill_result["order"]["filled_price"]) == Decimal("2401.00")
    assert fill_result["position"]["status"] == "OPEN"
    position_id = fill_result["position"]["id"]

    # 7. 行情上涨后，BUY 持仓产生浮动盈利。
    client.put(
        "/api/v1/market/quotes/XAUUSD",
        json={"price": "2410.50"},
    )
    position_response = client.get(f"/api/v1/positions/{position_id}")
    assert position_response.status_code == 200
    position = position_response.json()
    assert Decimal(position["current_price"]) == Decimal("2410.50")
    assert Decimal(position["unrealized_pnl"]) == Decimal("0.95")

    # 8. 再次改变价格后平仓，浮动盈亏转为已实现盈亏。
    client.put(
        "/api/v1/market/quotes/XAUUSD",
        json={"price": "2408.00"},
    )
    close_response = client.post(f"/api/v1/positions/{position_id}/close")
    assert close_response.status_code == 200
    closed_position = close_response.json()
    assert closed_position["status"] == "CLOSED"
    assert Decimal(closed_position["realized_pnl"]) == Decimal("0.70")
    assert Decimal(closed_position["unrealized_pnl"]) == Decimal("0")

    # 9. 已实现盈利应同时更新账户余额和累计盈亏。
    account_response = client.get(f"/api/v1/accounts/{account_id}")
    assert account_response.status_code == 200
    account = account_response.json()
    assert Decimal(account["balance"]) == Decimal("100000.70")
    assert Decimal(account["realized_pnl"]) == Decimal("0.70")

    # 10. 终态不能再次变化：重复平仓和撤销已成交订单都返回 409。
    second_close = client.post(f"/api/v1/positions/{position_id}/close")
    assert second_close.status_code == 409
    assert second_close.json()["error"]["code"] == "POSITION_ALREADY_CLOSED"

    cancel_filled = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert cancel_filled.status_code == 409
    assert cancel_filled.json()["error"]["code"] == (
        "INVALID_ORDER_TRANSITION"
    )


def test_sell_position_profits_when_price_falls(
    client: TestClient,
    account_id: str,
) -> None:
    """验证 SELL 持仓在行情下跌时产生正盈亏。"""
    client.put(
        "/api/v1/market/quotes/XAUUSD",
        json={"price": "100.00"},
    )
    order_response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        json={
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": "2.00",
            "requested_price": "100.00",
        },
    )
    order_id = order_response.json()["id"]
    fill_response = client.post(f"/api/v1/orders/{order_id}/fill")
    position_id = fill_response.json()["position"]["id"]

    client.put(
        "/api/v1/market/quotes/XAUUSD",
        json={"price": "90.00"},
    )
    position = client.get(f"/api/v1/positions/{position_id}").json()
    assert Decimal(position["unrealized_pnl"]) == Decimal("20.00")
