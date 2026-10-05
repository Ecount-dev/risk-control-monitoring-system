"""标准事件契约：事件描述已发生的事实，不是要求执行的命令。

第一步只定义契约并由原有同步 Service 记录事件；没有 EventBus 消费循环。
行情/信号/成交可直接使用不可变领域对象；订单/持仓必须先做快照。
"""

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import ClassVar
from uuid import UUID, uuid4

from app.domain.entities import Fill, MarketQuote, RiskDecision, utc_now
from app.domain.enums import OrderStatus, PositionStatus
from app.domain.market import Bar, Tick
from app.domain.signals import Signal
from app.domain.snapshots import AccountSettlement, OrderSnapshot, PositionSnapshot
from app.domain.state_machine import ALLOWED_ORDER_TRANSITIONS
from app.domain.validation import DomainValidationError, aware_utc, clean_text


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """事件信封；所有时间明确带 UTC 时区。

    event_id：该事件的唯一身份，不是订单 ID。
    correlation_id：把一次信号/订单生命周期的事件串起来。
    causation_id：已知的直接上游事件；独立操作允许为空。
    event_time：业务发生时间，历史数据必须显式提供历史时间。
    recorded_at：本进程生成记录的时间，目前使用墙上时钟。
    """

    event_time: datetime
    source: str
    correlation_id: UUID
    causation_id: UUID | None = None
    event_id: UUID = field(default_factory=uuid4)
    recorded_at: datetime = field(default_factory=utc_now)
    schema_version: int = field(default=1, init=False)
    event_type: ClassVar[str]
    payload_type: ClassVar[type]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", clean_text(self.source, "source"))
        for name in ("event_time", "recorded_at"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        for name in ("event_id", "correlation_id", "causation_id"):
            value = getattr(self, name)
            if name == "causation_id" and value is None:
                continue
            if not isinstance(value, UUID):
                raise DomainValidationError(name, "必须是 UUID")
        if not isinstance(self.payload, self.payload_type):
            raise DomainValidationError("payload", f"必须是 {self.payload_type.__name__}")

    def to_dict(self) -> dict:
        """导出可 JSON 编码的数据，不转换 Decimal 为 float。

        仅提供展示/写入接口；恢复、版本迁移与可靠持久化是后续 Journal 的工作。
        """
        return {"event_type": self.event_type, **_json_value(self)}


@dataclass(frozen=True, slots=True, kw_only=True)
class QuoteUpdated(DomainEvent):
    """旧模拟单价格更新；不假装它是带真实点差的 Tick。"""

    event_type: ClassVar[str] = "market.quote_updated"
    payload_type: ClassVar[type] = MarketQuote
    payload: MarketQuote


@dataclass(frozen=True, slots=True, kw_only=True)
class TickReceived(DomainEvent):
    event_type: ClassVar[str] = "market.tick_received"
    payload_type: ClassVar[type] = Tick
    payload: Tick


@dataclass(frozen=True, slots=True, kw_only=True)
class BarClosed(DomainEvent):
    event_type: ClassVar[str] = "market.bar_closed"
    payload_type: ClassVar[type] = Bar
    payload: Bar

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.event_time < self.payload.close_time:
            raise DomainValidationError("event_time", "不能在 K 线收盘前发布 BarClosed")


@dataclass(frozen=True, slots=True, kw_only=True)
class SignalGenerated(DomainEvent):
    event_type: ClassVar[str] = "strategy.signal_generated"
    payload_type: ClassVar[type] = Signal
    payload: Signal


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderCreated(DomainEvent):
    event_type: ClassVar[str] = "order.created"
    payload_type: ClassVar[type] = OrderSnapshot
    payload: OrderSnapshot

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.payload.status != OrderStatus.PENDING_RISK:
            raise DomainValidationError("payload.status", "新订单必须是 PENDING_RISK")


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskEvaluated(DomainEvent):
    event_type: ClassVar[str] = "risk.evaluated"
    payload_type: ClassVar[type] = RiskDecision
    payload: RiskDecision


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderStateChanged(DomainEvent):
    """本项目 ACCEPTED 仍表示本地风控通过，尚不是 Broker 接单确认。"""

    event_type: ClassVar[str] = "order.state_changed"
    payload_type: ClassVar[type] = OrderSnapshot
    payload: OrderSnapshot
    previous_status: OrderStatus

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        targets = ALLOWED_ORDER_TRANSITIONS.get(self.previous_status, set())
        if self.payload.status not in targets:
            raise DomainValidationError("payload.status", "事件必须描述合法的订单状态转换")


@dataclass(frozen=True, slots=True, kw_only=True)
class FillRecorded(DomainEvent):
    event_type: ClassVar[str] = "execution.fill_recorded"
    payload_type: ClassVar[type] = Fill
    payload: Fill


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionOpened(DomainEvent):
    event_type: ClassVar[str] = "position.opened"
    payload_type: ClassVar[type] = PositionSnapshot
    payload: PositionSnapshot

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.payload.status != PositionStatus.OPEN:
            raise DomainValidationError("payload.status", "开仓事件必须包含 OPEN 持仓")


@dataclass(frozen=True, slots=True, kw_only=True)
class PositionClosed(DomainEvent):
    event_type: ClassVar[str] = "position.closed"
    payload_type: ClassVar[type] = PositionSnapshot
    payload: PositionSnapshot

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.payload.status != PositionStatus.CLOSED:
            raise DomainValidationError("payload.status", "平仓事件必须包含 CLOSED 持仓")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountSettled(DomainEvent):
    event_type: ClassVar[str] = "account.settled"
    payload_type: ClassVar[type] = AccountSettlement
    payload: AccountSettlement


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        # 用整数微秒保存周期，避免 total_seconds() 的 float 舍入。
        return (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    return value
