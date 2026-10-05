"""行情接口：MT5 实时报价与旧模拟行情明确分离。"""

from fastapi import APIRouter, Request

from app.core.errors import ConflictError
from app.dependencies import LiveMarketAdapterDep, MarketServiceDep
from app.schemas.market import (
    MarketCollectorStatusResponse, MarketInstrumentResponse, MarketQuoteResponse,
    MarketQuoteUpdate, MarketTickResponse,
)


router = APIRouter(prefix="/market", tags=["market"])


@router.get("/collector/status", response_model=MarketCollectorStatusResponse)
def get_collector_status(request: Request):
    """查看后台采集、重试、落盘及时间基准诊断，不触发 MT5 下单。"""
    collector = request.app.state.market_collector
    if collector is None:
        raise ConflictError(
            code="MARKET_COLLECTOR_DISABLED",
            message="行情采集器未启用；正常 MT5 模式启动时默认启用",
        )
    return collector.status()


@router.get("/ticks/{symbol}", response_model=MarketTickResponse)
def get_tick(symbol: str, adapter: LiveMarketAdapterDep, request: Request):
    """从已登录的 MT5 终端拉取最新 Tick，不写入模拟报价库。"""
    tick = adapter.get_tick(symbol)
    delta_seconds = int((tick.event_time - tick.received_at).total_seconds())
    max_age = request.app.state.max_tick_age_seconds
    # 若数据源时间领先本机太多，不能直接拿二者差值证明报价仍新鲜。
    stale = None if delta_seconds > max_age else -delta_seconds > max_age
    return MarketTickResponse(
        symbol=tick.instrument_id.symbol,
        venue=tick.instrument_id.venue,
        broker_symbol=adapter.broker_symbol_for(symbol),
        bid=tick.bid,
        ask=tick.ask,
        spread=tick.spread,
        event_time=tick.event_time,
        received_at=tick.received_at,
        is_stale=stale,
        source_time_delta_seconds=delta_seconds,
    )


@router.get("/instruments/{symbol}", response_model=MarketInstrumentResponse)
def get_instrument(symbol: str, adapter: LiveMarketAdapterDep):
    """读取券商合约大小、最小价格变动和允许的手数步长。"""
    instrument = adapter.get_instrument(symbol)
    return MarketInstrumentResponse(
        symbol=instrument.id.symbol,
        venue=instrument.id.venue,
        broker_symbol=adapter.broker_symbol_for(symbol),
        quote_currency=instrument.quote_currency,
        volume_unit=instrument.volume_unit.value,
        contract_size=instrument.contract_size,
        price_increment=instrument.price_increment,
        volume_increment=instrument.volume_increment,
        min_volume=instrument.min_volume,
        max_volume=instrument.max_volume,
    )


def require_simulation(request: Request) -> None:
    """不允许真实行情与假成交链互相污染。"""
    if request.app.state.market_source != "sim":
        raise ConflictError(
            code="SIMULATED_MARKET_DISABLED",
            message="MT5 行情模式下不能使用手动报价；请读取 /api/v1/market/ticks/{symbol}",
        )


@router.put("/quotes/{symbol}", response_model=MarketQuoteResponse, deprecated=True)
def update_quote(
    symbol: str,
    payload: MarketQuoteUpdate,
    service: MarketServiceDep,
    request: Request,
):
    """新增或替换某个交易品种的最新模拟报价。"""
    require_simulation(request)
    return service.update_quote(symbol, payload.price)


@router.get("/quotes/{symbol}", response_model=MarketQuoteResponse, deprecated=True)
def get_quote(symbol: str, service: MarketServiceDep, request: Request):
    """查询某个交易品种的最新模拟报价。"""
    require_simulation(request)
    return service.get_quote(symbol)
