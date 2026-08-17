"""策略在某一个时点看到的只读市场快照。"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.entities import Account, MarketQuote, Position, RiskRule


@dataclass(frozen=True, slots=True)
class MarketContext:
    """策略做决策时能读到的信息快照。

    设计为 frozen 是为了提醒策略「只能读取、不要修改」。注意：Account 等内部
    实体本身仍是可变对象，策略应当把它们当作只读数据来使用。
    """

    symbol: str                        # 当前触发策略的品种（已标准化，如 XAUUSD）
    quote: MarketQuote                 # 该品种最新报价
    account: Account                   # 账户余额、状态
    open_positions: tuple[Position, ...]  # 当前未平仓持仓
    risk_rule: RiskRule                # 账户风控规则（策略可据此控制仓位）
