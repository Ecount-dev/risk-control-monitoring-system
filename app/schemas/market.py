"""模拟单价格和 MT5 实时双边报价的独立响应模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class MarketQuoteUpdate(BaseModel):
    """手动更新行情时提交的数据；价格必须大于零。"""

    price: Annotated[
        Decimal,
        Field(gt=0, max_digits=18, decimal_places=6),
    ]


class MarketQuoteResponse(BaseModel):
    """一个品种的最新价格及更新时间。"""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    price: Decimal
    updated_at: datetime


class MarketTickResponse(BaseModel):
    """真实双边报价，不能用单个 price 冒充可成交价。"""

    symbol: str
    venue: str
    broker_symbol: str
    bid: Decimal
    ask: Decimal
    spread: Decimal
    event_time: datetime
    received_at: datetime
    # 时间基准不一致时不能可靠判断过期，返回 null 而不是误报正常。
    is_stale: bool | None
    # MT5 时间减去本机接收时间；包含网络延迟，不等同于精确时区偏移。
    source_time_delta_seconds: int


class MarketInstrumentResponse(BaseModel):
    """券商给出的合约规格；手数和价格步长可按券商而变。"""

    symbol: str
    venue: str
    broker_symbol: str
    quote_currency: str
    volume_unit: str
    contract_size: Decimal
    price_increment: Decimal
    volume_increment: Decimal
    min_volume: Decimal
    max_volume: Decimal


class CollectedTickResponse(BaseModel):
    """最近一条已落盘行情，含券商原始时间戳。"""

    broker_symbol: str
    source_time_msc: int
    event_time: datetime
    received_at: datetime
    bid: Decimal
    ask: Decimal
    source_time_delta_seconds: int


class MarketCollectorStatusResponse(BaseModel):
    """后台采集运行状态；IDLE 不代表断线，可能只是尚无新报价。"""

    symbol: str
    state: str
    poll_interval_seconds: float
    polls: int
    new_ticks: int
    duplicates: int
    consecutive_errors: int
    last_error_code: str | None
    last_poll_at: datetime | None
    last_success_at: datetime | None
    last_new_tick_at: datetime | None
    persisted_ticks: int
    latest: CollectedTickResponse | None
    time_basis_status: str
    complete_tick_stream: bool
