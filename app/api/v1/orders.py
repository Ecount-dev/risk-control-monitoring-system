"""订单提交、查询、撤销、风控结果和模拟成交接口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.dependencies import OrderServiceDep, PositionServiceDep
from app.domain.enums import OrderStatus
from app.schemas.order import FillOrderResponse, OrderCreate, OrderResponse
from app.schemas.risk import RiskDecisionResponse


router = APIRouter(tags=["orders"])


@router.post(
    "/accounts/{account_id}/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    account_id: UUID,
    payload: OrderCreate,
    service: OrderServiceDep,
):
    """创建订单并同步执行风控，返回 ACCEPTED 或 REJECTED。"""
    return service.create(
        account_id,
        symbol=payload.symbol,
        side=payload.side,
        volume=payload.volume,
        requested_price=payload.requested_price,
    )


@router.get(
    "/accounts/{account_id}/orders",
    response_model=list[OrderResponse],
)
def list_orders(
    account_id: UUID,
    service: OrderServiceDep,
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """查询账户订单；status 和 limit 都是可选查询参数。"""
    return service.list_for_account(
        account_id,
        status=order_status,
        limit=limit,
    )


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: UUID, service: OrderServiceDep):
    """根据订单 ID 查询单个订单。"""
    return service.get(order_id)


@router.get(
    "/orders/{order_id}/risk-decision",
    response_model=RiskDecisionResponse,
)
def get_risk_decision(order_id: UUID, service: OrderServiceDep):
    """查询订单当时通过或未通过风控的具体原因。"""
    return service.get_risk_decision(order_id)


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(order_id: UUID, service: OrderServiceDep):
    """撤销已接受但尚未成交的订单。"""
    return service.cancel(order_id)


@router.post("/orders/{order_id}/fill", response_model=FillOrderResponse)
def fill_order(
    order_id: UUID,
    order_service: OrderServiceDep,
    position_service: PositionServiceDep,
):
    """使用最新模拟行情成交订单，并生成一条独立持仓。"""
    order, position = order_service.fill(order_id)

    # 成交接口同时返回变化后的订单和新持仓，便于客户端继续后续流程。
    return {
        "order": order,
        "position": position_service.to_view(position),
    }
