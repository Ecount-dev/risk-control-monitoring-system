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
from app.domain.market import InstrumentId
from app.domain.validation import (
    DomainValidationError, aware_utc, clean_text, enum_value, require_uuid,
    trading_decimal,
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
    # 保留旧 API 的 symbol/volume 字段；内部用 venue 区分交易场所。
    venue: str = "SIM"
    strategy_id: str | None = None
    signal_id: UUID | None = None

    def __post_init__(self) -> None:
        instrument = InstrumentId(self.symbol, self.venue)
        self.symbol, self.venue = instrument.symbol, instrument.venue
        self.side = enum_value(OrderSide, self.side, "side")
        self.status = enum_value(OrderStatus, self.status, "status")
        require_uuid(self.id, "id")
        require_uuid(self.account_id, "account_id")
        if self.signal_id is not None:
            require_uuid(self.signal_id, "signal_id")
        trading_decimal(self.volume, "volume")
        trading_decimal(self.requested_price, "requested_price")
        if self.filled_price is not None:
            trading_decimal(self.filled_price, "filled_price")
        if self.strategy_id is not None:
            self.strategy_id = clean_text(self.strategy_id, "strategy_id")
        self.created_at = aware_utc(self.created_at, "created_at")
        self.updated_at = aware_utc(self.updated_at, "updated_at")

    @property
    def instrument_id(self) -> InstrumentId:
        return InstrumentId(self.symbol, self.venue)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """某个订单在下单时得到的风控审计记录。"""

    order_id: UUID
    passed: bool
    id: UUID = field(default_factory=uuid4)
    failed_rule: str | None = None
    reason: str | None = None
    evaluated_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class MarketQuote:
    """某个交易品种当前最新的一条模拟行情。"""

    symbol: str
    price: Decimal
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", clean_text(self.symbol, "symbol", upper=True))
        trading_decimal(self.price, "price")
        object.__setattr__(self, "updated_at", aware_utc(self.updated_at, "updated_at"))


@dataclass(frozen=True, slots=True)
class Fill:
    """一次已经发生的成交事实；创建时即完整，不允许随后补写 position_id。

    不等同于订单：未来一笔订单可以对应多次 Fill。目前服务仍为一次全部成交。
    commission 暂只记录；旧模拟结算使用零费用，后续 PortfolioEngine 再处理费用。
    """

    kind: ExecutionKind
    symbol: str
    side: OrderSide
    volume: Decimal
    price: Decimal
    account_id: UUID
    order_id: UUID | None = None
    position_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    executed_at: datetime = field(default_factory=utc_now)
    venue: str = "SIM"
    strategy_id: str | None = None
    broker_trade_id: str | None = None
    commission: Decimal = Decimal("0")
    commission_currency: str | None = None

    def __post_init__(self) -> None:
        instrument = InstrumentId(self.symbol, self.venue)
        object.__setattr__(self, "symbol", instrument.symbol)
        object.__setattr__(self, "venue", instrument.venue)
        object.__setattr__(self, "side", enum_value(OrderSide, self.side, "side"))
        object.__setattr__(self, "kind", enum_value(ExecutionKind, self.kind, "kind"))
        require_uuid(self.id, "id")
        require_uuid(self.account_id, "account_id")
        for name in ("order_id", "position_id"):
            if getattr(self, name) is not None:
                require_uuid(getattr(self, name), name)
        if self.order_id is None and self.position_id is None:
            raise DomainValidationError("fill", "至少需要关联 order_id 或 position_id")
        trading_decimal(self.volume, "volume")
        trading_decimal(self.price, "price")
        trading_decimal(self.commission, "commission", allow_zero=True)
        if self.commission != 0 and self.commission_currency is None:
            raise DomainValidationError("commission_currency", "非零费用必须指定币种")
        if self.commission_currency is not None:
            object.__setattr__(self, "commission_currency", clean_text(self.commission_currency, "commission_currency", upper=True))
        if self.strategy_id is not None:
            object.__setattr__(self, "strategy_id", clean_text(self.strategy_id, "strategy_id"))
        object.__setattr__(self, "executed_at", aware_utc(self.executed_at, "executed_at"))

    @property
    def instrument_id(self) -> InstrumentId:
        return InstrumentId(self.symbol, self.venue)


# 旧导入路径继续可用；这是同一个类，避免保留两套成交模型。
# 新构造代码需要显式传 account_id。
Execution = Fill


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
    venue: str = "SIM"
    strategy_id: str | None = None

    def __post_init__(self) -> None:
        instrument = InstrumentId(self.symbol, self.venue)
        self.symbol, self.venue = instrument.symbol, instrument.venue
        self.side = enum_value(OrderSide, self.side, "side")
        self.status = enum_value(PositionStatus, self.status, "status")
        for name in ("id", "account_id", "opening_order_id"):
            require_uuid(getattr(self, name), name)
        if self.strategy_id is not None:
            self.strategy_id = clean_text(self.strategy_id, "strategy_id")
        trading_decimal(self.volume, "volume")
        trading_decimal(self.open_price, "open_price")
        self.opened_at = aware_utc(self.opened_at, "opened_at")
        if self.close_price is not None:
            trading_decimal(self.close_price, "close_price")
        if self.closed_at is not None:
            self.closed_at = aware_utc(self.closed_at, "closed_at")

    @property
    def instrument_id(self) -> InstrumentId:
        return InstrumentId(self.symbol, self.venue)
