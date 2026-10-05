"""把领域异常统一转换为稳定的 HTTP 错误格式。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import DomainError
from app.domain.validation import DomainValidationError


async def domain_error_handler(
    request: Request,
    exc: DomainError,
) -> JSONResponse:
    """将 DomainError 序列化为客户端可处理的 JSON。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """让所有 DomainError 子类共用同一个处理器。"""
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(DomainValidationError, domain_validation_error_handler)


async def domain_validation_error_handler(
    request: Request, exc: DomainValidationError,
) -> JSONResponse:
    """领域层报告字段约束，接口层才决定将其映射为 HTTP 422。"""
    return JSONResponse(status_code=422, content={"error": {
        "code": "INVALID_DOMAIN_VALUE", "message": str(exc),
        "details": {"field": exc.field},
    }})
