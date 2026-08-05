"""账户和账户级风控规则接口。"""

from uuid import UUID

from fastapi import APIRouter, status

from app.dependencies import AccountServiceDep
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate
from app.schemas.risk import RiskRuleResponse, RiskRuleUpdate


router = APIRouter(tags=["accounts"])


@router.post(
    "/accounts",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_account(
    payload: AccountCreate,
    service: AccountServiceDep,
):
    """创建模拟账户，并自动为它生成一套默认风控规则。"""
    return service.create(
        name=payload.name,
        initial_balance=payload.initial_balance,
    )


@router.get("/accounts/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: UUID,
    service: AccountServiceDep,
):
    """按账户 ID 查询账户余额、状态和已实现盈亏。"""
    return service.get(account_id)


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: UUID,
    payload: AccountUpdate,
    service: AccountServiceDep,
):
    """启用或禁用账户；禁用账户的新订单会被风控拒绝。"""
    return service.update_status(account_id, payload.status)


@router.get(
    "/accounts/{account_id}/risk-rules",
    response_model=RiskRuleResponse,
)
def get_risk_rule(
    account_id: UUID,
    service: AccountServiceDep,
):
    """查询指定账户当前使用的风控规则。"""
    return service.get_risk_rule(account_id)


@router.put(
    "/accounts/{account_id}/risk-rules",
    response_model=RiskRuleResponse,
)
def update_risk_rule(
    account_id: UUID,
    payload: RiskRuleUpdate,
    service: AccountServiceDep,
):
    """完整替换账户风控规则，因此这里使用 HTTP PUT。"""
    return service.update_risk_rule(
        account_id,
        max_order_volume=payload.max_order_volume,
        max_order_notional=payload.max_order_notional,
        max_open_positions=payload.max_open_positions,
        allowed_symbols=tuple(payload.allowed_symbols),
        daily_loss_limit=payload.daily_loss_limit,
    )
