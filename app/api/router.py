"""汇总并注册 v1 版本的所有业务路由。"""

from fastapi import APIRouter

from app.api.v1 import accounts, market, orders, positions


# 统一版本前缀便于未来增加 /api/v2，而不破坏已有客户端。
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(accounts.router)
api_router.include_router(orders.router)
api_router.include_router(market.router)
api_router.include_router(positions.router)
