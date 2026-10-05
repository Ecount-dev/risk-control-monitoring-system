"""不依赖 HTTP 的领域约束；API、策略、未来的回测入口共用。

类型注解不会在运行时拦住 float、NaN 或负数。因此在对象构造时校验，
并用独立异常报告字段；HTTP 状态码由接口层决定。
"""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TypeVar
from uuid import UUID

EnumType = TypeVar("EnumType", bound=Enum)


class DomainValidationError(ValueError):
    """输入不能构成合法的领域对象。"""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}")


def clean_text(value: str, field: str, *, upper: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(field, "必须是非空字符串")
    value = value.strip()
    return value.upper() if upper else value


def trading_decimal(
    value: Decimal, field: str, *, allow_zero: bool = False,
) -> Decimal:
    """要求有限的十进制数；不把二进制 float 隐式转换为金额。"""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DomainValidationError(field, '必须是有限 Decimal，例如 Decimal("0.1")')
    if value < 0 or (value == 0 and not allow_zero):
        raise DomainValidationError(field, "必须大于等于 0" if allow_zero else "必须大于 0")
    return value


def aware_utc(value: datetime, field: str) -> datetime:
    """拒绝无时区时间，把明确带时区的时间统一成 UTC。"""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(field, "必须包含时区")
    return value.astimezone(timezone.utc)


def enum_value(enum_type: type[EnumType], value, field: str) -> EnumType:
    """字符串可显式转为枚举；非法值统一报告为领域校验错误。"""
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise DomainValidationError(field, f"必须是有效的 {enum_type.__name__}") from exc


def require_uuid(value: UUID, field: str) -> None:
    if not isinstance(value, UUID):
        raise DomainValidationError(field, "必须是 UUID")
