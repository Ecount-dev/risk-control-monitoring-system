"""账户和账户风控配置的业务操作。"""

from decimal import Decimal
from uuid import UUID

from app.core.errors import NotFoundError
from app.domain.entities import Account, RiskRule
from app.domain.enums import AccountStatus
from app.repositories.memory import InMemoryDatabase


class AccountService:
    """协调账户实体、默认风控规则和数据存储。"""

    def __init__(self, db: InMemoryDatabase) -> None:
        self.db = db

    def create(self, *, name: str, initial_balance: Decimal) -> Account:
        """创建账户，并保证它从一开始就拥有默认风控规则。"""
        account = Account(name=name, balance=initial_balance)
        rule = RiskRule(account_id=account.id)

        # 两个对象属于同一个创建用例，因此放在同一临界区写入。
        with self.db.lock:
            self.db.accounts[account.id] = account
            self.db.risk_rules[account.id] = rule

        return account

    def get(self, account_id: UUID) -> Account:
        """查询账户；不存在时抛出可转换为 HTTP 404 的业务异常。"""
        with self.db.lock:
            account = self.db.accounts.get(account_id)
            if account is None:
                raise NotFoundError(
                    code="ACCOUNT_NOT_FOUND",
                    message="账户不存在",
                    details={"account_id": str(account_id)},
                )
            return account

    def update_status(
        self,
        account_id: UUID,
        status: AccountStatus,
    ) -> Account:
        """切换账户启用状态。"""
        with self.db.lock:
            account = self.get(account_id)
            account.status = status
            return account

    def get_risk_rule(self, account_id: UUID) -> RiskRule:
        """取得账户风控规则，并先验证账户本身存在。"""
        with self.db.lock:
            self.get(account_id)
            return self.db.risk_rules[account_id]

    def update_risk_rule(
        self,
        account_id: UUID,
        *,
        max_order_volume: Decimal,
        max_order_notional: Decimal,
        max_open_positions: int,
        allowed_symbols: tuple[str, ...],
        daily_loss_limit: Decimal,
    ) -> RiskRule:
        """用客户端提交的完整配置替换旧规则。"""
        with self.db.lock:
            self.get(account_id)
            rule = RiskRule(
                account_id=account_id,
                max_order_volume=max_order_volume,
                max_order_notional=max_order_notional,
                max_open_positions=max_open_positions,
                allowed_symbols=allowed_symbols,
                daily_loss_limit=daily_loss_limit,
            )
            self.db.risk_rules[account_id] = rule
            return rule
