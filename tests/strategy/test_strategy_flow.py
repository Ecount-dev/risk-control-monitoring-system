"""验证「策略 → 风控 → 成交」整条链路，以及策略信号与风控的边界。"""

from decimal import Decimal
from uuid import uuid4

from app.domain.entities import Account, MarketQuote, RiskRule
from app.domain.enums import OrderStatus, PositionStatus
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService
from app.services.order_service import OrderService
from app.services.position_service import PositionService
from app.strategy.context import MarketContext
from app.strategy.ma_cross import MovingAverageCrossoverStrategy
from app.strategy.runner import StrategyRunner


def make_context(price: str) -> MarketContext:
    """构造一个只有价格有意义的上下文，供策略单元测试使用。"""
    account_id = uuid4()
    return MarketContext(
        symbol="XAUUSD",
        quote=MarketQuote(symbol="XAUUSD", price=Decimal(price)),
        account=Account(name="unit", balance=Decimal("100000")),
        open_positions=(),
        risk_rule=RiskRule(account_id=account_id),
    )


def test_golden_cross_emits_buy_then_death_cross_emits_sell() -> None:
    """快线上穿慢线产生 BUY，下穿产生 SELL。"""
    strategy = MovingAverageCrossoverStrategy(
        fast_window=2, slow_window=3, order_volume=Decimal("0.1")
    )

    # 前三个价格用于建立均线，无信号。
    assert strategy.on_tick(make_context("100")) is None
    assert strategy.on_tick(make_context("100")) is None
    assert strategy.on_tick(make_context("100")) is None

    # 价格上跳，快线(105)上穿慢线(103.33) → 金叉 BUY。
    buy = strategy.on_tick(make_context("110"))
    assert buy is not None
    assert buy.side.value == "BUY"
    assert buy.symbol == "XAUUSD"

    # 先回落到 100（快慢线仍在上方，无死叉）。
    assert strategy.on_tick(make_context("100")) is None

    # 价格继续下跳，快线(95)下穿慢线(100) → 死叉 SELL。
    sell = strategy.on_tick(make_context("90"))
    assert sell is not None
    assert sell.side.value == "SELL"


def _make_account(db: InMemoryDatabase) -> Account:
    """创建账户并放开 XAUUSD 的单笔 1 手限制，让 0.1 手信号能通过风控。"""
    accounts = AccountService(db)
    account = accounts.create(
        name="strategy-demo", initial_balance=Decimal("100000")
    )
    accounts.update_risk_rule(
        account.id,
        max_order_volume=Decimal("1"),
        max_order_notional=Decimal("100000"),
        max_open_positions=5,
        allowed_symbols=("XAUUSD",),
        daily_loss_limit=Decimal("1000"),
    )
    return account


def test_strategy_signal_flows_through_risk_and_fill() -> None:
    """完整链路：金叉信号 → 下单 → 通过风控(ACCEPTED) → 成交 → 持仓与盈亏。"""
    db = InMemoryDatabase()
    account = _make_account(db)

    strategy = MovingAverageCrossoverStrategy(
        fast_window=2, slow_window=3, order_volume=Decimal("0.1")
    )
    runner = StrategyRunner(db, strategy, account.id)

    # 建立均线，此阶段无信号。
    assert runner.on_quote("XAUUSD", Decimal("100")) is None
    assert runner.on_quote("XAUUSD", Decimal("100")) is None
    assert runner.on_quote("XAUUSD", Decimal("100")) is None

    # 金叉触发：策略信号经 OrderService 创建订单并通过风控。
    order = runner.on_quote("XAUUSD", Decimal("110"))
    assert order is not None
    assert order.status == OrderStatus.ACCEPTED

    # 模拟成交，生成持仓。
    _, position = OrderService(db).fill(order.id)
    assert position.status == PositionStatus.OPEN

    # 行情继续上涨，BUY 持仓出现浮动盈利。
    MarketDataService(db).update_quote("XAUUSD", Decimal("120"))
    view = PositionService(db).to_view(position)
    assert view["unrealized_pnl"] == Decimal("1.0")  # (120 - 110) * 0.1


def test_strategy_signal_cannot_bypass_risk() -> None:
    """策略发出的超限信号仍会被风控拒绝，并留下审计记录。"""
    db = InMemoryDatabase()
    account = _make_account(db)  # max_order_volume = 1

    strategy = MovingAverageCrossoverStrategy(
        fast_window=2, slow_window=3, order_volume=Decimal("5")  # 超过 1 手限制
    )
    runner = StrategyRunner(db, strategy, account.id)

    runner.on_quote("XAUUSD", Decimal("100"))
    runner.on_quote("XAUUSD", Decimal("100"))
    runner.on_quote("XAUUSD", Decimal("100"))
    order = runner.on_quote("XAUUSD", Decimal("110"))  # 金叉

    assert order is not None
    assert order.status == OrderStatus.REJECTED
    assert order.reject_reason is not None
    assert "超过限制" in order.reject_reason

    # 风控决定留痕，便于审计。
    decision = OrderService(db).get_risk_decision(order.id)
    assert decision.passed is False
    assert decision.failed_rule == "MAX_ORDER_VOLUME_EXCEEDED"
