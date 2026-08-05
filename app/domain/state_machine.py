"""订单状态转换规则。"""

from app.core.errors import ConflictError
from app.domain.entities import Order, utc_now
from app.domain.enums import OrderStatus


# 终态对应空集合，因此 REJECTED、FILLED、CANCELLED 都不能再被修改。
ALLOWED_ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING_RISK: {OrderStatus.ACCEPTED, OrderStatus.REJECTED},
    OrderStatus.ACCEPTED: {OrderStatus.FILLED, OrderStatus.CANCELLED},
    OrderStatus.REJECTED: set(),
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
}


def transition_order(order: Order, target: OrderStatus) -> None:
    """校验并执行一次订单状态转换。

    所有服务都通过这一入口改变状态，防止业务代码绕过生命周期规则。
    """
    if target not in ALLOWED_ORDER_TRANSITIONS[order.status]:
        raise ConflictError(
            code="INVALID_ORDER_TRANSITION",
            message=f"{order.status} 订单不能转换为 {target}",
            details={
                "order_id": str(order.id),
                "current_status": order.status,
                "target_status": target,
            },
        )

    order.status = target
    # 状态变化属于订单更新，需要同步刷新修改时间。
    order.updated_at = utc_now()
