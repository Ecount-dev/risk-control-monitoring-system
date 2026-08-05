"""交易领域中的有限状态和方向枚举。"""

from enum import StrEnum


class AccountStatus(StrEnum):
    """账户是否允许继续提交新订单。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class OrderSide(StrEnum):
    """订单或持仓的买卖方向。"""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    """订单从风控到终态的生命周期。"""

    PENDING_RISK = "PENDING_RISK"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class PositionStatus(StrEnum):
    """持仓生命周期；订单成交后才会产生持仓。"""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExecutionKind(StrEnum):
    """成交记录是开仓成交还是平仓成交。"""

    OPEN = "OPEN"
    CLOSE = "CLOSE"
