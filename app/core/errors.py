"""业务异常类型。

Service 抛出与 HTTP 框架无关的业务异常，统一处理器再把它转换为 JSON 响应。
"""

from typing import Any


class DomainError(Exception):
    """所有可预期业务错误的基类。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    """请求的账户、订单、行情或持仓不存在。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=404,
            code=code,
            message=message,
            details=details,
        )


class ConflictError(DomainError):
    """资源存在，但当前状态不允许执行请求的动作。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=409,
            code=code,
            message=message,
            details=details,
        )
