"""第一步可运行示例：标准对象 → 事件 → 原项目交易闭环。

运行：python -m examples.domain_flow
全部数据仅在这次进程的 InMemoryDatabase 里。
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import Bar, Instrument, InstrumentId, Tick, VolumeUnit
from app.domain.events import BarClosed, TickReceived
from app.repositories.memory import InMemoryDatabase
from app.services.account_service import AccountService
from app.services.market_service import MarketDataService
from app.services.order_service import OrderService
from app.services.position_service import PositionService
from app.strategy.ma_cross import MovingAverageCrossoverStrategy
from app.strategy.runner import StrategyRunner


def main() -> None:
    db = InMemoryDatabase()
    account = AccountService(db).create(name="contract-demo", initial_balance=Decimal("100000"))

    # 这些是示范性 SIM 合约规格，绝非 MT5 或任何券商的 XAUUSD 实际规格。
    instrument = Instrument(
        id=InstrumentId("XAUUSD", "SIM"), quote_currency="USD",
        volume_unit=VolumeUnit.UNIT, contract_size=Decimal("1"),
        price_increment=Decimal("0.01"), volume_increment=Decimal("0.1"),
        min_volume=Decimal("0.1"), max_volume=Decimal("10"),
    )
    instrument.validate_volume(Decimal("0.1"))

    # Tick 和 Bar 用于展示未来 MarketDataAdapter 的输出契约。
    # 第一阶段它们被直接写到内存事件记录器，暂不驱动旧均线策略。
    ts = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    tick = Tick(instrument_id=instrument.id, bid=Decimal("109.99"),
                ask=Decimal("110.01"), event_time=ts, received_at=ts)
    db.record_event(TickReceived(event_time=tick.event_time, source="example",
                                 correlation_id=account.id, payload=tick))
    bar = Bar(instrument_id=instrument.id, interval=timedelta(minutes=1),
              open_time=ts, close_time=ts + timedelta(minutes=1),
              open=Decimal("100"), high=Decimal("110"), low=Decimal("99"),
              close=Decimal("110"), volume=Decimal("0"))
    db.record_event(BarClosed(event_time=bar.close_time, source="example",
                              correlation_id=account.id, payload=bar))

    # 下面复用原项目：单价模拟行情 → 均线信号 → 风控 → 下单 → 成交 → 平仓。
    runner = StrategyRunner(
        db, MovingAverageCrossoverStrategy(fast_window=2, slow_window=3),
        account.id, strategy_id="demo-ma-xauusd",
    )
    for price in ("100", "100", "100"):
        assert runner.on_quote("XAUUSD", Decimal(price)) is None
    order = runner.on_quote("XAUUSD", Decimal("110"))
    assert order is not None, "预期第四个报价产生金叉"
    _, position = OrderService(db).fill(order.id)
    MarketDataService(db).update_quote("XAUUSD", Decimal("120"))
    PositionService(db).close(position.id)

    # 事件按创建顺序输出。Signal 与其订单/成交/持仓共享 correlation_id。
    # 英文标签可避免部分 Windows 终端按旧编码显示中文时出现乱码。
    print(f"Instrument: {instrument.id}; Tick spread: {tick.spread}")
    print(f"Order: {order.status}; Position: {position.status}; Balance: {account.balance}")
    for event in db.events:
        print(f"{event.event_type:27} correlation={event.correlation_id}")


if __name__ == "__main__":
    main()
