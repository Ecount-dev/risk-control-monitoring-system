"""模拟行情接口。第一版通过 HTTP 手动写入最新价格。"""

from fastapi import APIRouter

from app.dependencies import MarketServiceDep
from app.schemas.market import MarketQuoteResponse, MarketQuoteUpdate


router = APIRouter(prefix="/market/quotes", tags=["market"])


@router.put("/{symbol}", response_model=MarketQuoteResponse)
def update_quote(
    symbol: str,
    payload: MarketQuoteUpdate,
    service: MarketServiceDep,
):
    """新增或替换某个交易品种的最新模拟报价。"""
    return service.update_quote(symbol, payload.price)


@router.get("/{symbol}", response_model=MarketQuoteResponse)
def get_quote(symbol: str, service: MarketServiceDep):
    """查询某个交易品种的最新模拟报价。"""
    return service.get_quote(symbol)
