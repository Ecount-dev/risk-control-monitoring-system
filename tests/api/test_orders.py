"""订单接口的失败路径和边界行为测试。"""

from fastapi.testclient import TestClient


def test_invalid_order_fields_return_422(
    client: TestClient,
    account_id: str,
) -> None:
    """字段级输入错误应由 Pydantic/FastAPI 在进入业务层前返回 422。"""
    cases = [
        {
            "symbol": " ",
            "side": "BUY",
            "volume": "0.10",
            "requested_price": "100",
        },
        {
            "symbol": "XAUUSD",
            "side": "HOLD",
            "volume": "0.10",
            "requested_price": "100",
        },
        {
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "0",
            "requested_price": "100",
        },
        {
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "0.10",
            "requested_price": "-1",
        },
    ]

    for payload in cases:
        response = client.post(
            f"/api/v1/accounts/{account_id}/orders",
            json=payload,
        )
        assert response.status_code == 422


def test_cancelled_order_cannot_be_filled(
    client: TestClient,
    account_id: str,
) -> None:
    """验证状态机禁止 CANCELLED -> FILLED。"""
    order_response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        json={
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "0.10",
            "requested_price": "100",
        },
    )
    order_id = order_response.json()["id"]
    cancel_response = client.post(f"/api/v1/orders/{order_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "CANCELLED"

    fill_response = client.post(f"/api/v1/orders/{order_id}/fill")
    assert fill_response.status_code == 409
    assert fill_response.json()["error"]["code"] == "INVALID_ORDER_TRANSITION"


def test_fill_requires_a_current_quote(
    client: TestClient,
    account_id: str,
) -> None:
    """没有行情时不能成交，而且订单应继续保持 ACCEPTED。"""
    order_response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        json={
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "0.10",
            "requested_price": "100",
        },
    )
    order_id = order_response.json()["id"]

    fill_response = client.post(f"/api/v1/orders/{order_id}/fill")
    assert fill_response.status_code == 409
    assert fill_response.json()["error"]["code"] == (
        "MARKET_QUOTE_UNAVAILABLE"
    )

    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["status"] == "ACCEPTED"


def test_disabled_account_order_is_audited_as_rejected(
    client: TestClient,
    account_id: str,
) -> None:
    """禁用账户的订单仍然保存，并留下明确的风控审计结果。"""
    update_response = client.patch(
        f"/api/v1/accounts/{account_id}",
        json={"status": "DISABLED"},
    )
    assert update_response.status_code == 200

    order_response = client.post(
        f"/api/v1/accounts/{account_id}/orders",
        json={
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "0.10",
            "requested_price": "100",
        },
    )
    assert order_response.status_code == 201
    order = order_response.json()
    assert order["status"] == "REJECTED"

    decision = client.get(
        f"/api/v1/orders/{order['id']}/risk-decision"
    ).json()
    assert decision["passed"] is False
    assert decision["failed_rule"] == "ACCOUNT_DISABLED"


def test_unknown_order_returns_structured_404(client: TestClient) -> None:
    """不存在的订单返回统一错误结构，而不是服务器堆栈。"""
    response = client.get("/api/v1/orders/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORDER_NOT_FOUND"
