"""与 FastAPI、Pydantic 和数据库无关的交易领域实体。

这些数据类表达系统内部真正保存和处理的对象；schemas 目录中的模型则表达
HTTP 客户端能提交和看到的数据，二者用途不同。
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.domain.enums import (
    AccountStatus,
    ExecutionKind,
    OrderSide,
    OrderStatus,
    PositionStatus,
)


def utc_now() -> datetime:
    """统一生成带 UTC 时区的时间，避免无时区时间造成比较错误。"""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Account:
    """模拟交易账户及其已结算资金结果。"""

    name: str
    balance: Decimal
    id: UUID = field(default_factory=uuid4)
    status: AccountStatus = AccountStatus.ACTIVE
    realized_pnl: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RiskRule:
    """一个账户当前使用的风控阈值。"""

    account_id: UUID
    max_order_volume: Decimal = Decimal("10")
    max_order_notional: Decimal = Decimal("100000")
    max_open_positions: int = 5
    allowed_symbols: tuple[str, ...] = ("XAUUSD", "EURUSD")
    daily_loss_limit: Decimal = Decimal("1000")


@dataclass(slots=True)
class Order:
    """客户的交易意图及其处理状态。

    requested_price 是下单时的参考价，filled_price 才是模拟成交时的实际价格。
    """

    account_id: UUID
    symbol: str
    side: OrderSide
    volume: Decimal
    requested_price: Decimal
    id: UUID = field(default_factory=uuid4)
    status: OrderStatus = OrderStatus.PENDING_RISK
    reject_reason: str | None = None
    filled_price: Decimal | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RiskDecision:
    """某个订单在下单时得到的风控审计记录。"""

    order_id: UUID
    passed: bool
    id: UUID = field(default_factory=uuid4)
    failed_rule: str | None = None
    reason: str | None = None
    evaluated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MarketQuote:
    """某个交易品种当前最新的一条模拟行情。"""

    symbol: str
    price: Decimal
    updated_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Execution:
    """一次实际发生的开仓或平仓成交记录。"""

    kind: ExecutionKind
    symbol: str
    side: OrderSide
    volume: Decimal
    price: Decimal
    order_id: UUID | None = None
    position_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    executed_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Position:
    """开仓订单成交后形成的持仓。

    第一版采用对冲式简化模型：每个开仓订单生成一条独立持仓，不合并同品种仓位。
    """

    account_id: UUID
    opening_order_id: UUID
    symbol: str
    side: OrderSide
    volume: Decimal
    open_price: Decimal
    id: UUID = field(default_factory=uuid4)
    status: PositionStatus = PositionStatus.OPEN
    close_price: Decimal | None = None
    realized_pnl: Decimal | None = None
    opened_at: datetime = field(default_factory=utc_now)
    closed_at: datetime | None = None
