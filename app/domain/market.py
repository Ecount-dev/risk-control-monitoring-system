"""标准合约、双边 Tick 和已收盘 Bar。

这些对象不主动联网，也不聚合 K 线。未来 Adapter 负责构造它们，
FeatureEngine 负责使用它们。合约规格必须来自数据源/显式配置。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.domain.validation import (
    DomainValidationError, aware_utc, clean_text, enum_value, trading_decimal,
)


@dataclass(frozen=True, slots=True)
class InstrumentId:
    """品种 + 场所共同标识合约；SIM 与 MT5 的同名品种不能混用。

    symbol 是内部标准代码。券商原始代码/后缀由未来 Gateway 映射。
    """

    symbol: str
    venue: str = "SIM"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", clean_text(self.symbol, "symbol", upper=True))
        object.__setattr__(self, "venue", clean_text(self.venue, "venue", upper=True))

    def __str__(self) -> str:
        return f"{self.symbol}@{self.venue}"


class VolumeUnit(StrEnum):
    """数量单位必须明确；旧模拟业务使用 UNIT，MT5 配置可使用 LOT。"""

    UNIT = "UNIT"
    LOT = "LOT"


@dataclass(frozen=True, slots=True, kw_only=True)
class Instrument:
    """合约静态规格；contract_size 表示每个 volume 单位对应的合约量。

    暂只定义规格与检查方法，不改变旧 API 的简化盈亏公式。
    不能把某券商 XAUUSD 的合约大小硬编码成所有券商通用值。
    """

    id: InstrumentId
    quote_currency: str
    volume_unit: VolumeUnit
    contract_size: Decimal
    price_increment: Decimal
    volume_increment: Decimal
    min_volume: Decimal
    max_volume: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.id, InstrumentId):
            raise DomainValidationError("id", "必须是 InstrumentId")
        object.__setattr__(self, "quote_currency", clean_text(self.quote_currency, "quote_currency", upper=True))
        object.__setattr__(self, "volume_unit", enum_value(VolumeUnit, self.volume_unit, "volume_unit"))
        for name in ("contract_size", "price_increment", "volume_increment", "min_volume", "max_volume"):
            trading_decimal(getattr(self, name), name)
        if self.min_volume > self.max_volume:
            raise DomainValidationError("min_volume", "不能超过 max_volume")
        self.validate_volume(self.min_volume)
        self.validate_volume(self.max_volume)

    def validate_price(self, price: Decimal) -> None:
        trading_decimal(price, "price")
        if price % self.price_increment != 0:
            raise DomainValidationError("price", "不符合合约最小变动价位")

    def validate_volume(self, volume: Decimal) -> None:
        trading_decimal(volume, "volume")
        if not self.min_volume <= volume <= self.max_volume:
            raise DomainValidationError("volume", "超出合约数量范围")
        if volume % self.volume_increment != 0:
            raise DomainValidationError("volume", "不符合合约数量步长")


@dataclass(frozen=True, slots=True, kw_only=True)
class Tick:
    """双边报价：bid 为可卖价，ask 为可买价；不是旧单价格的别名。

    event_time 是数据源时间，received_at 是本系统收到它的时间。
    二者可能受时钟偏差影响，因此不强制 received_at >= event_time。
    """

    instrument_id: InstrumentId
    bid: Decimal
    ask: Decimal
    event_time: datetime
    received_at: datetime
    # 保留券商 Python API 原始毫秒值；不按猜测的时区偏移改写。
    source_time_msc: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise DomainValidationError("instrument_id", "必须是 InstrumentId")
        trading_decimal(self.bid, "bid")
        trading_decimal(self.ask, "ask")
        if self.ask < self.bid:
            raise DomainValidationError("ask", "不能小于 bid")
        for name in ("event_time", "received_at"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        if self.source_time_msc is not None and (
            not isinstance(self.source_time_msc, int)
            or isinstance(self.source_time_msc, bool)
            or self.source_time_msc <= 0
        ):
            raise DomainValidationError("source_time_msc", "必须是正整数毫秒时间戳")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True, kw_only=True)
class Bar:
    """已收盘 K 线；覆盖 [open_time, close_time)，close_time 才能交给策略。

    interval 明确周期。volume 的统计口径必须由适配器说明（成交量或 Tick 数），
    不应直接当作订单手数；本对象不处理尚未收盘的实时 K 线。
    """

    instrument_id: InstrumentId
    interval: timedelta
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_id, InstrumentId):
            raise DomainValidationError("instrument_id", "必须是 InstrumentId")
        for name in ("open_time", "close_time"):
            object.__setattr__(self, name, aware_utc(getattr(self, name), name))
        if not isinstance(self.interval, timedelta) or self.interval <= timedelta(0):
            raise DomainValidationError("interval", "必须是正的 timedelta")
        if self.close_time - self.open_time != self.interval:
            raise DomainValidationError("close_time", "必须等于 open_time + interval")
        for name in ("open", "high", "low", "close"):
            trading_decimal(getattr(self, name), name)
        trading_decimal(self.volume, "volume", allow_zero=True)
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise DomainValidationError("OHLC", "必须满足 low <= open/close <= high")
