"""FastAPI 应用入口。

Uvicorn 启动时会导入本模块中的 ``app`` 对象。应用的创建、内存数据库、
异常处理器和全部路由都在这里组装。
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI

from app.adapters.market_data import MarketDataAdapter
from app.adapters.mt5_market_data import MT5MarketDataAdapter
from app.api.router import api_router
from app.core.exception_handlers import register_exception_handlers
from app.repositories.memory import InMemoryDatabase
from app.repositories.tick_sqlite import SQLiteTickRepository
from app.services.market_collector import MarketDataCollector


def create_app(
    db: InMemoryDatabase | None = None,
    *,
    market_source: Literal["mt5", "sim"] | None = None,
    mt5_adapter: MarketDataAdapter | None = None,
    enable_market_collector: bool | None = None,
    tick_db_path: str | Path | None = None,
) -> FastAPI:
    """创建并配置一个 FastAPI 应用。

    测试会传入全新的内存数据库，保证用例之间互不影响；正常启动时不传，
    则为当前进程创建一份数据库。使用工厂函数也方便以后替换为真实数据库。
    """
    # 正常启动以 MT5 行情为默认；注入测试数据库时默认保留原有模拟流程。
    source = market_source or os.getenv("MARKET_SOURCE") or ("sim" if db is not None else "mt5")
    if source not in {"mt5", "sim"}:
        raise ValueError("MARKET_SOURCE 只能是 mt5 或 sim")
    # 正常服务默认采集；注入测试库的应用默认不创建后台线程/磁盘文件。
    enabled_env = os.getenv("MT5_COLLECTOR_ENABLED")
    if enabled_env is not None and enabled_env not in {"0", "1"}:
        raise ValueError("MT5_COLLECTOR_ENABLED 只能是 0 或 1")
    collector_enabled = (
        enable_market_collector
        if enable_market_collector is not None
        else (enabled_env == "1" if enabled_env is not None else db is None)
    )
    if source != "mt5" and collector_enabled:
        raise ValueError("后台 MT5 行情采集只允许在 mt5 模式启动")
    collector_enabled = collector_enabled and source == "mt5"

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        collector = None
        try:
            if application.state.collector_enabled:
                repository = SQLiteTickRepository(application.state.tick_db_path)
                collector = MarketDataCollector(
                    application.state.mt5_adapter,
                    repository,
                    symbol=application.state.collector_symbol,
                    poll_interval_seconds=application.state.poll_interval_seconds,
                    time_tolerance_seconds=application.state.max_tick_age_seconds,
                )
                application.state.market_collector = collector
                collector.start()
            yield
        finally:
            stopped = collector.stop() if collector is not None else True
            # 仅断开 Python IPC；不会关闭用户正在运行的终端。
            adapter = application.state.mt5_adapter
            if stopped and adapter is not None and hasattr(adapter, "close"):
                adapter.close()

    application = FastAPI(
        title="交易研究与风控 API",
        version="0.1.0",
        description=(
            "MT5 只读实时行情已接入；订单、持仓和风控仍是内存模拟，"
            "在 MT5 行情模式下禁用模拟下单/成交，绝不会向券商发送订单。"
        ),
        lifespan=lifespan,
    )
    # state 用来保存与应用生命周期一致的对象。所有请求共享这一份数据库。
    application.state.db = db or InMemoryDatabase()
    application.state.db.market_source = source
    application.state.market_source = source
    if source == "mt5":
        mapping = json.loads(os.getenv("MT5_SYMBOL_MAP", "{}"))
        if not isinstance(mapping, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in mapping.items()
        ):
            raise ValueError("MT5_SYMBOL_MAP 必须是字符串到字符串的 JSON 对象")
        application.state.mt5_adapter = mt5_adapter or MT5MarketDataAdapter(
            terminal_path=os.getenv("MT5_TERMINAL_PATH"),
            symbol_map=mapping,
        )
    else:
        application.state.mt5_adapter = None
    application.state.max_tick_age_seconds = int(os.getenv("MT5_MAX_TICK_AGE_SECONDS", "30"))
    if application.state.max_tick_age_seconds <= 0:
        raise ValueError("MT5_MAX_TICK_AGE_SECONDS 必须大于 0")
    application.state.collector_enabled = collector_enabled
    application.state.market_collector = None
    if collector_enabled:
        default_db_path = Path(__file__).resolve().parents[1] / "data" / "mt5_ticks.sqlite3"
        application.state.tick_db_path = tick_db_path or os.getenv("MT5_TICK_DB_PATH") or default_db_path
        application.state.collector_symbol = os.getenv("MT5_COLLECTOR_SYMBOL", "XAUUSD")
        application.state.poll_interval_seconds = float(os.getenv("MT5_POLL_INTERVAL_SECONDS", "1.0"))
    else:
        application.state.tick_db_path = None

    # 先注册公共能力，再挂载业务路由。
    register_exception_handlers(application)
    application.include_router(api_router)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """供浏览器、部署平台或监控系统判断服务是否存活。"""
        return {"status": "ok"}

    return application


# ``uvicorn app.main:app`` 中最后的 app 指的就是这个对象。
app = create_app()
