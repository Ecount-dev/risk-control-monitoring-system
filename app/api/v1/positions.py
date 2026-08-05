"""持仓查询和模拟平仓接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.dependencies import PositionServiceDep
from app.domain.enums import PositionStatus
from app.schemas.position import PositionResponse


router = APIRouter(tags=["positions"])


@router.get(
    "/accounts/{account_id}/positions",
    response_model=list[PositionResponse],
)
def list_positions(
    account_id: UUID,
    service: PositionServiceDep,
    position_status: Annotated[
        PositionStatus | None,
        Query(alias="status"),
    ] = None,
):
    """查询账户持仓，并按需过滤 OPEN 或 CLOSED。"""
    positions = service.list_for_account(account_id, status=position_status)

    # current_price 和 unrealized_pnl 是动态字段，需要逐条结合最新行情计算。
    return [service.to_view(position) for position in positions]


@router.get("/positions/{position_id}", response_model=PositionResponse)
def get_position(position_id: UUID, service: PositionServiceDep):
    """查询单个持仓及其按最新行情计算出的浮动盈亏。"""
    return service.to_view(service.get(position_id))


@router.post(
    "/positions/{position_id}/close",
    response_model=PositionResponse,
)
def close_position(position_id: UUID, service: PositionServiceDep):
    """按最新模拟行情平仓，并把已实现盈亏计入账户余额。"""
    return service.to_view(service.close(position_id))
