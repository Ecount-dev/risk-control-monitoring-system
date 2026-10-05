"""FastAPI 依赖注入配置。

路由只声明自己需要哪种 Service，不负责创建数据库和业务服务，从而让接口层
保持轻量，也让测试可以替换依赖。
"""

from typing import Annotated

from fastapi import Depends, Request

from app.adapters.market_data import MarketDataAdapter
from app.core.errors import ConflictError
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService
from app.services.order_service import OrderService
from app.services.position_service import PositionService


def get_db(request: Request) -> InMemoryDatabase:
    """从当前 FastAPI 应用中取得共享的内存数据库。"""
    return request.app.state.db


# Annotated 同时保留类型信息，并告诉 FastAPI 该参数由 get_db 提供。
Database = Annotated[InMemoryDatabase, Depends(get_db)]


def get_account_service(db: Database) -> AccountService:
    """为当前请求创建账户服务，并注入共享数据库。"""
    return AccountService(db)


def get_market_service(db: Database) -> MarketDataService:
    """为当前请求创建行情服务。"""
    return MarketDataService(db)


def get_live_market_adapter(request: Request) -> MarketDataAdapter:
    """实时行情路由只能在 MT5 模式读取终端，不回退到模拟报价。"""
    adapter = request.app.state.mt5_adapter
    if adapter is None:
        raise ConflictError(
            code="MT5_MARKET_MODE_REQUIRED",
            message="当前是模拟模式；请设置 MARKET_SOURCE=mt5 后重启",
        )
    return adapter


def get_order_service(db: Database) -> OrderService:
    """为当前请求创建订单服务。"""
    return OrderService(db)


def get_position_service(db: Database) -> PositionService:
    """为当前请求创建持仓服务。"""
    return PositionService(db)


# 路由使用这些类型别名后，函数签名更短，也仍能获得编辑器类型提示。
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
MarketServiceDep = Annotated[MarketDataService, Depends(get_market_service)]
LiveMarketAdapterDep = Annotated[MarketDataAdapter, Depends(get_live_market_adapter)]
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
PositionServiceDep = Annotated[PositionService, Depends(get_position_service)]
