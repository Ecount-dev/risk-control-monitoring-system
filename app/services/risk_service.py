"""订单成交前的账户级风险检查。"""

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.entities import Account, Order, RiskDecision, RiskRule
from app.domain.enums import AccountStatus, PositionStatus
from app.repositories.memory import InMemoryDatabase


class RiskService:
    """按照固定顺序执行风控，并返回可审计的决定对象。"""

    def __init__(self, db: InMemoryDatabase) -> None:
        self.db = db

    def evaluate(
        self,
        *,
        account: Account,
        order: Order,
        rule: RiskRule,
    ) -> RiskDecision:
        """评估一个新订单，命中第一条失败规则后立即拒绝。

        Order 领域对象已经保证正数等基础约束；这里检查依赖账户状态和实时数据的
        业务规则。返回决定而不是抛异常，因为风控拒绝是正常交易结果。
        """
        # 先检查成本最低且最基础的规则，再进行需要遍历持仓的检查。
        if account.status != AccountStatus.ACTIVE:
            return self._reject(order, "ACCOUNT_DISABLED", "账户已被禁用")

        if order.symbol not in rule.allowed_symbols:
            return self._reject(
                order,
                "SYMBOL_NOT_ALLOWED",
                f"账户不允许交易 {order.symbol}",
            )

        if order.volume > rule.max_order_volume:
            return self._reject(
                order,
                "MAX_ORDER_VOLUME_EXCEEDED",
                f"订单数量超过限制 {rule.max_order_volume}",
            )

        # 名义金额是数量与参考价格的乘积，第一版暂不计算杠杆和保证金。
        notional = order.volume * order.requested_price
        if notional > rule.max_order_notional:
            return self._reject(
                order,
                "MAX_ORDER_NOTIONAL_EXCEEDED",
                f"订单名义金额 {notional} 超过限制 {rule.max_order_notional}",
            )

        # 只统计当前账户的 OPEN 持仓，不包含已经平仓的历史记录。
        open_positions = sum(
            1
            for position in self.db.positions.values()
            if position.account_id == account.id
            and position.status == PositionStatus.OPEN
        )
        if open_positions >= rule.max_open_positions:
            return self._reject(
                order,
                "MAX_OPEN_POSITIONS_REACHED",
                f"未平仓持仓数已达到限制 {rule.max_open_positions}",
            )

        daily_realized_pnl = self._daily_realized_pnl(account.id)
        if daily_realized_pnl <= -rule.daily_loss_limit:
            return self._reject(
                order,
                "DAILY_LOSS_LIMIT_REACHED",
                f"当日已实现亏损已达到限制 {rule.daily_loss_limit}",
            )

        return RiskDecision(order_id=order.id, passed=True)

    def _daily_realized_pnl(self, account_id) -> Decimal:
        """汇总账户在 UTC 当日已经平仓的持仓盈亏。"""
        today = datetime.now(timezone.utc).date()
        return sum(
            (
                position.realized_pnl or Decimal("0")
                for position in self.db.positions.values()
                if position.account_id == account_id
                and position.closed_at is not None
                and position.closed_at.date() == today
            ),
            start=Decimal("0"),
        )

    @staticmethod
    def _reject(order: Order, failed_rule: str, reason: str) -> RiskDecision:
        """用统一结构创建拒绝决定，供订单和审计接口使用。"""
        return RiskDecision(
            order_id=order.id,
            passed=False,
            failed_rule=failed_rule,
            reason=reason,
        )
