"""[역할] 기준값·경로·보안 설정을 한곳에 모은다(값은 기획서·구현명세의 예시값)."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
DATA_DIR = BASE_DIR / "data"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
LOG_PATH = DATA_DIR / "loan_service.log"
SECRET_PATH = DATA_DIR / ".secret_key"

# ---- 규제·심사 기준 (예시값, reg_param 테이블에도 같은 값으로 저장) ----
DSR_LIMIT = Decimal("0.40")            # DSR 한도 40%
STRESS_ADD = Decimal("1.0")            # 스트레스 가산금리 +1.0%p
LTV_LIMIT = Decimal("0.70")            # 주택담보 LTV 70%
JEONSE_RATIO_LIMIT = Decimal("0.90")   # (선순위+보증금)/시세 90%
JEONSE_LOAN_RATIO = Decimal("0.80")    # 보증금의 80%
AUTO_LOAN_RATIO = Decimal("0.90")      # 차량가의 90%
DEPOSIT_LOAN_RATIO = Decimal("0.95")   # 예금 잔액의 95%
MIN_INCOME = 20_000_000                # 최소 연 소득 2,000만원
MIN_TENURE_MONTHS = 12                 # 급여소득자 최소 재직 12개월
MIN_CREDIT_SCORE = 600                 # 신용평점 기준
MULTI_DEBT_LIMIT = 5                   # 다중채무 건수 기준
INQUIRY_LIMIT = 7                      # 최근 6개월 조회 건수 기준
SUIT_MAX_BURDEN = Decimal("0.70")      # 적합성 상환 부담률 70%
LEGAL_MAX_RATE = Decimal("20.0")       # 법정 최고 금리 연 20%
BASE_RATE = Decimal("3.10")            # 기준금리(예시)
LATE_ADD = Decimal("3.0")              # 지연배상금 가산 +3%p
CARD_USAGE_MIN = 300_000               # 카드 사용 우대 기준: 직전 달 카드 사용액 30만원(예시)

# ---- 대환 ----
REFI_MIN_SINCE = 6                     # 실행 후 6개월
REFI_MIN_REMAIN = 6                    # 남은 기간 6개월
REFI_FEE_FREE_MONTHS = 36              # 3년 경과 시 중도상환수수료 면제
STAMP_DUTY_THRESHOLD = 50_000_000      # 인지세 고객 부담 기준(예시)
STAMP_DUTY_CUSTOMER = 35_000

# ---- 대출관리 ----
PREPAY_FEE_RATE = Decimal("0.012")     # 중도상환수수료율 1.2%(예시)
WITHDRAW_DAYS = 14                     # 청약철회 14일
RATE_CUT_THRESHOLD = Decimal("4.5")    # 금리인하요구 수용 기준(프로토타입 단순화)
RATE_CUT_STEP = Decimal("0.3")

# ---- 증빙 파일 ----
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_UPLOADS_PER_APP = 20               # 신청 1건당 업로드 파일 수
UPLOAD_DIR = DATA_DIR / "evidence"     # 업로드 파일 저장 위치(파일 이름은 서버가 만든 id)
MAGIC = {".pdf": b"%PDF", ".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}

# ---- 유효기간 ----
APPLICATION_TTL_DAYS = 7
REVIEW_TTL_DAYS = 30

# ---- 보안 ----
RATE_LIMIT_PER_MIN = 30                # 회원·출처별 외부 조회 분당 상한
LLM_PROVIDER = os.environ.get("LOAN_LLM_PROVIDER", "offline")  # offline = 외부 호출 없이 템플릿 생성
