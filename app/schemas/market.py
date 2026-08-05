"""模拟市场最新报价的请求与响应模型。"""

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
