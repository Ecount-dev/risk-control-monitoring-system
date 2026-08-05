"""第一版使用的进程内数据存储。"""

from threading import RLock
from uuid import UUID

from app.domain.entities import (
    Account,
    Execution,
    MarketQuote,
    Order,
    Position,
    RiskDecision,
    RiskRule,
)


class InMemoryDatabase:
    """供学习版本使用的进程内数据库。

    它没有持久化能力，程序重启后所有数据都会消失。字段按资源类型拆成字典，
    将来可以用 SQLAlchemy 仓储替换，而不改变 HTTP 接口的含义。
    """

    def __init__(self) -> None:
        # FastAPI 的同步路由可能在线程池中并发执行，RLock 保护复合读写操作。
        # 使用可重入锁是因为一个 Service 持锁后可能继续调用另一个也会加锁的 Service。
        self.lock = RLock()

        # UUID 是主键；行情使用标准化后的 symbol 作为键。
        self.accounts: dict[UUID, Account] = {}
        self.risk_rules: dict[UUID, RiskRule] = {}
        self.orders: dict[UUID, Order] = {}
        self.risk_decisions: dict[UUID, RiskDecision] = {}
        self.quotes: dict[str, MarketQuote] = {}
        self.executions: dict[UUID, Execution] = {}
        self.positions: dict[UUID, Position] = {}
