"""FastAPI 应用入口。

Uvicorn 启动时会导入本模块中的 ``app`` 对象。应用的创建、内存数据库、
异常处理器和全部路由都在这里组装。
"""

from fastapi import FastAPI

from app.api.router import api_router
from app.core.exception_handlers import register_exception_handlers
from app.repositories.memory import InMemoryDatabase


def create_app(db: InMemoryDatabase | None = None) -> FastAPI:
    """创建并配置一个 FastAPI 应用。

    测试会传入全新的内存数据库，保证用例之间互不影响；正常启动时不传，
    则为当前进程创建一份数据库。使用工厂函数也方便以后替换为真实数据库。
    """
    application = FastAPI(
        title="模拟交易订单与风控系统",
        version="0.1.0",
        description=(
            "用于学习 FastAPI、订单状态机、风控、持仓和盈亏计算。"
            "本系统不连接真实交易账户。"
        ),
    )
    # state 用来保存与应用生命周期一致的对象。所有请求共享这一份数据库。
    application.state.db = db or InMemoryDatabase()

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
