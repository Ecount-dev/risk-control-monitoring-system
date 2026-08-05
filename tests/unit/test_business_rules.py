"""不经过 HTTP，直接验证状态机和盈亏公式。"""

from decimal import Decimal

import pytest

from app.core.errors import ConflictError
from app.domain.entities import Order
from app.domain.enums import OrderSide, OrderStatus
from app.domain.state_machine import transition_order
from app.services.position_service import PositionService


def test_order_state_machine_rejects_invalid_transition() -> None:
    """订单成交后已经是终态，不能再转为已撤销。"""
    order = Order(
        account_id=__import__("uuid").uuid4(),
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=Decimal("0.1"),
        requested_price=Decimal("2400"),
    )
    transition_order(order, OrderStatus.ACCEPTED)
    transition_order(order, OrderStatus.FILLED)

    with pytest.raises(ConflictError):
        transition_order(order, OrderStatus.CANCELLED)


@pytest.mark.parametrize(
    ("side", "open_price", "current_price", "volume", "expected"),
    [
        (OrderSide.BUY, "100", "110", "2", "20"),
        (OrderSide.BUY, "100", "90", "2", "-20"),
        (OrderSide.SELL, "100", "90", "2", "20"),
        (OrderSide.SELL, "100", "110", "2", "-20"),
    ],
)
def test_pnl_direction(
    side: OrderSide,
    open_price: str,
    current_price: str,
    volume: str,
    expected: str,
) -> None:
    """覆盖 BUY/SELL 在上涨和下跌时的四种盈亏方向。"""
    pnl = PositionService.calculate_pnl(
        side=side,
        open_price=Decimal(open_price),
        current_price=Decimal(current_price),
        volume=Decimal(volume),
    )
    assert pnl == Decimal(expected)
