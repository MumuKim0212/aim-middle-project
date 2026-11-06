"""계좌 API(계좌.md 4장). 로그인 필요 API 는 전부 `Depends(current_user)` 로 보호하고, user 는 세션에서만 얻는다.

  GET  /api/products                         상품 안내(로그인 없이)
  GET  /api/accounts                         내 계좌 목록(?status=closed, ?purpose=card_payment)
  POST /api/accounts                         계좌 개설          GET /api/accounts/{id}                 계좌 상세
  GET  /api/accounts/{id}/transactions       거래 내역          GET /api/accounts/{id}/interest        이자 조회
  POST /api/accounts/{id}/deposit|pay|auto-pay|close            GET /api/accounts/{id}/close-preview   해지 미리 보기
  GET  /api/transfers/recipient|recent       예금주 확인·최근 계좌   POST /api/transfers                    이체
  GET|POST /api/favorites, DELETE /api/favorites/{id}           자주 쓰는 계좌
  POST /api/dev/accounts/{id}/maturity, /api/dev/auto-pay/run   개발 모드(APP_ENV=dev)에서만
"""
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as m
from ..auth.deps import current_user, require_pin_verified
from ..db import get_db
from . import service as svc

router = APIRouter(prefix="/api", tags=["accounts"])
dev_router = APIRouter(prefix="/api/dev", tags=["dev"])

AccountId = Annotated[int, Path(ge=1, le=2**63 - 1)]
Won = Annotated[int, Field(strict=True)]  # "abc"·"100"·true 는 받지 않는다(AF-04). 범위는 서비스가 검사한다


class OpenIn(BaseModel):
    productType: Literal["checking", "deposit", "savings"]
    agreed: bool = False
    alias: str | None = None
    isPrimary: bool = False
    amount: Won | None = None
    termMonths: Won | None = None
    monthlyAmount: Won | None = None
    paymentDay: Won | None = None
    autoPay: bool = True
    linkedAccountId: Won | None = None


class AmountIn(BaseModel):
    amount: Won


class TransferIn(BaseModel):
    fromAccountId: Won
    amount: Won
    toAccountId: Won | None = None
    toAccountNo: str | None = None
    memo: str | None = Field(default=None, max_length=50)


class AutoPayIn(BaseModel):
    enabled: bool


class CloseIn(BaseModel):
    receivingAccountId: Won | None = None


class FavoriteIn(BaseModel):
    accountNo: str
    displayName: str | None = Field(default=None, max_length=20)


@router.get("/products")
def products(db: Session = Depends(get_db)):
    return svc.list_products(db)


@router.get("/accounts")
def accounts(status: Literal["active", "closed"] = "active", purpose: str | None = None,
             user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.list_accounts(db, user, status=status, purpose=purpose)


@router.post("/accounts", status_code=201)
def open_account(body: OpenIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.open_account(
        db, user, body.productType, agreed=body.agreed, alias=body.alias, is_primary=body.isPrimary, amount=body.amount,
        term_months=body.termMonths, monthly_amount=body.monthlyAmount, payment_day=body.paymentDay,
        auto_pay=body.autoPay, linked_account_id=body.linkedAccountId)


@router.get("/accounts/{account_id}")
def account_detail(account_id: AccountId, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_account(db, user, account_id)


@router.get("/accounts/{account_id}/transactions")
def transactions(account_id: AccountId, period: Literal["1w", "1m", "3m", "custom"] = "1m",
                 date_from: date | None = Query(default=None, alias="from"), date_to: date | None = Query(default=None, alias="to"),
                 type: Literal["all", "deposit", "withdraw"] = "all", page: int = Query(default=1, ge=1, le=10_000),
                 user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_transactions(db, user, account_id, period=period, date_from=date_from, date_to=date_to,
                                type_=type, page=page)


@router.get("/accounts/{account_id}/interest")
def interest(account_id: AccountId, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.get_interest(db, user, account_id)


@router.post("/accounts/{account_id}/deposit")
def deposit(account_id: AccountId, body: AmountIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.deposit(db, user, account_id, body.amount)


@router.post("/accounts/{account_id}/pay")
def pay(account_id: AccountId, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.pay_savings(db, user, account_id)


@router.post("/accounts/{account_id}/auto-pay")
def auto_pay(account_id: AccountId, body: AutoPayIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.set_auto_pay(db, user, account_id, body.enabled)


@router.get("/accounts/{account_id}/close-preview")
def close_preview(account_id: AccountId, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.preview_close(db, user, account_id)


@router.post("/accounts/{account_id}/close")
def close(account_id: AccountId, request: Request, body: CloseIn | None = None, user: m.User = Depends(current_user),
          db: Session = Depends(get_db)):
    """예적금 해지는 간편비밀번호 확인이 필요하다(저축예금 해지는 아니다, 공통.md 4장)."""
    return svc.close_account(db, user, account_id, receiving_account_id=body.receivingAccountId if body else None,
                             confirm_pin=lambda: require_pin_verified(request))


@router.get("/transfers/recipient")
def recipient(accountNo: str = Query(min_length=1, max_length=30), user: m.User = Depends(current_user),
              db: Session = Depends(get_db)):
    return svc.lookup_recipient(db, user, accountNo)


@router.get("/transfers/recent")
def recent(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.recent_accounts(db, user)


@router.post("/transfers")
def transfer(body: TransferIn, request: Request, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """간편비밀번호 확인(/api/auth/pin/verify)을 5분 안에 하지 않았으면 403 PIN_VERIFICATION_REQUIRED(AF-21)."""
    return svc.transfer(db, user, body.fromAccountId, body.amount, to_account_id=body.toAccountId,
                        to_account_no=body.toAccountNo, memo=body.memo, confirm_pin=lambda: require_pin_verified(request))


@router.get("/favorites")
def favorites(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.list_favorites(db, user)


@router.post("/favorites", status_code=201)
def add_favorite(body: FavoriteIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.add_favorite(db, user, body.accountNo, body.displayName)


@router.delete("/favorites/{favorite_id}", status_code=204)
def delete_favorite(favorite_id: AccountId, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    svc.delete_favorite(db, user, favorite_id)


@dev_router.post("/accounts/{account_id}/maturity")
def dev_maturity(account_id: AccountId, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return svc.dev_set_maturity(db, user, account_id)


@dev_router.post("/auto-pay/run")
def dev_auto_pay(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return {"paid": svc.run_auto_pay(db)}
