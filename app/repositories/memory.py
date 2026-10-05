"""第一版使用的进程内数据存储。"""

from threading import RLock
from collections import deque
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
from app.domain.events import DomainEvent


class InMemoryDatabase:
    """供学习版本使用的进程内数据库。

    它没有持久化能力，程序重启后所有数据都会消失。字段按资源类型拆成字典，
    将来可以用 SQLAlchemy 仓储替换，而不改变 HTTP 接口的含义。
    """

    def __init__(self, *, event_capacity: int = 10000) -> None:
        # 模拟服务可单独运行；应用工厂在 MT5 行情模式下将其改为 mt5。
        self.market_source = "sim"
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
        # 仅供第一步检查事件契约：有界的内存记录器，无订阅/消费/恢复能力。
        # 满后丢弃最旧事件；绝不能把它当成持久化 Event Journal。
        if event_capacity <= 0:
            raise ValueError("event_capacity 必须大于 0")
        self._events: deque[DomainEvent] = deque(maxlen=event_capacity)

    def record_event(self, event: DomainEvent) -> None:
        with self.lock:
            self._events.append(event)

    @property
    def events(self) -> tuple[DomainEvent, ...]:
        """返回只读容器，外部不能 append/clear 修改内部历史。"""
        with self.lock:
            return tuple(self._events)
