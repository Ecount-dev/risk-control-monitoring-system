"""把领域异常统一转换为稳定的 HTTP 错误格式。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import DomainError


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
