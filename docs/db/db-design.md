# 통합 DB 테이블 설계 (초안)

대상 브랜치: `feature/card`(카드·계좌 연동 명세) · `feature/ledger`(가계부 기획안) · `feature/loan`(대출 기획서 6종) · `main`(기획서/레퍼런스)
일반 계좌(김연준)는 브랜치·문서가 없어서 카드 명세 5절(서버 간 계약)과 2.10에서 역산해 **제안**으로 넣었다.

> 상태: 제안. 담당자 합의 전 초안이다. 카드 쪽 `backend-spec.md` 2절이 가장 구체적이라 **그쪽 규칙을 공통 규칙으로 채택**했다.

## 1. 공통 규칙 (카드 명세 2.1 기준)

| 항목 | 규칙 |
|---|---|
| DB | PostgreSQL 기준 (MySQL로도 옮길 수 있는 수준) |
| 금액 | `BIGINT`(원). 소수 없음 |
| 일시 / 날짜 | `TIMESTAMPTZ`(UTC 저장) / `DATE`. "오늘" 경계는 KST |
| ID | `VARCHAR(40)` 접두어 + ULID (`member_…`, `acc_…`, `card_…`, `loan_…`). 사전순 = 생성순 |
| enum | `VARCHAR` + `CHECK` (DB enum 타입 안 씀) |
| 공통 컬럼 | `created_at` 필수, 수정되는 테이블은 `updated_at` |
| FK | 같은 도메인 안에서는 FK. 도메인 간(`member_id`, `account_id`)은 **논리 참조**(FK 안 검) |
| 민감정보 | 카드 전체번호·계좌 PIN·카드 PIN은 저장 안 함. 대출 계좌번호·주민번호 등은 컬럼 암호화 |

## 2. 도메인 한눈에 보기

```
[공통]  members ─┬─ accounts ── account_pin_state
                 │            └─ account_transactions
                 └─ idempotency_keys / audit_log

[카드]  card_products 1─* cards 1─* card_status_history
                          └─ 1─* card_transactions (cancel → original_id)
        card_applications → cards,  card_issue_quota

[가계부] budgets 1─* category_budgets
        card_transactions 1─1 ledger_tx_category (분류)
        planned_outflows, payment_attempts, ledger_settings(모드)
        chat_sessions 1─* chat_messages,  rag_documents

[대출]  loan_application ─ consent_record / applicant_profile / suitability_result / evidence
                         ─ review_result / loan_terms / pricing / recommendation_log / explanation_record
        contract ─ repayment_schedule / collateral / disbursement
```

## 3. 공통·계좌 (김연준 담당 — 제안)

### `members`
| 컬럼 | 타입 | NULL | 설명 |
|---|---|:--:|---|
| `id` | VARCHAR(40) | X | PK |
| `login_id` | VARCHAR(50) | X | UNIQUE (가계부 초안의 `email` 대체 가능) |
| `password_hash` | VARCHAR(100) | X | |
| `name` | VARCHAR(30) | X | |
| `birth_date` | DATE | O | 카드 신청 만 19세 확인 (`getMember`) |
| `phone` | VARCHAR(13) | O | |
| `created_at` / `updated_at` | TIMESTAMPTZ | X | |

> `roles.md`에 로그인·회원 담당이 없다 (카드 명세 미결). 누가 만들지 먼저 정해야 한다.

### `accounts`
| 컬럼 | 타입 | NULL | 설명 |
|---|---|:--:|---|
| `id` | VARCHAR(40) | X | PK |
| `member_id` | VARCHAR(40) | X | FK → members |
| `bank_name` | VARCHAR(30) | X | |
| `account_no_enc` | VARCHAR(200) | X | 암호화 계좌번호 |
| `account_masked` | VARCHAR(20) | X | `****1234` |
| `balance` | BIGINT | X | `CHECK (balance >= 0)` |
| `purpose` | VARCHAR(20) | X | `general` \| `card_payment` \| `loan` … |
| `is_primary` | BOOLEAN | X | 가계부 "대표계좌" |
| `status` | VARCHAR(10) | X | `active` \| `closed` |
| `created_at` / `updated_at` | TIMESTAMPTZ | X | |

인덱스 `(member_id, status)`, `UNIQUE (member_id) WHERE is_primary`.

### `account_pin_state` (카드 명세 2.10 그대로)
`account_id` PK · `fail_count` SMALLINT(0~4) · `locked_until` TIMESTAMPTZ NULL · `updated_at`.

### `account_transactions` (입출금 — 제안)
`id`, `account_id` FK, `kind`(`deposit`/`withdraw`/`transfer_in`/`transfer_out`/`card_payment`/`loan_disbursement`/`loan_repayment`), `amount` BIGINT>0, `balance_after` BIGINT, `counterparty` VARCHAR(100), `memo`, `occurred_at`, `ref_type`/`ref_id`(카드 청구·대출 상환 등과 연결).
인덱스 `(account_id, occurred_at DESC, id DESC)`.

### `idempotency_keys` (카드 명세 2.9 → 대출 `Idempotency-Key`와 공용)
PK `(member_id, idem_key)` · `fingerprint` CHAR(64) · `response_status` SMALLINT NULL · `response_body` TEXT NULL · `created_at` · `expires_at`. 인덱스 `(expires_at)`.

### `audit_log` (대출 공통 감사 로그를 전 도메인 공용으로)
`id`, `entity`, `entity_id`, `action`, `before` JSONB, `after` JSONB, `actor`, `at`. 인덱스 `(entity, entity_id, at)`.

## 4. 카드 (김경민) — `backend-spec.md` 2.3~2.9 확정안 그대로

핵심만 요약한다. 컬럼·CHECK·인덱스는 원문이 정본이다.

| 테이블 | 핵심 컬럼 | 비고 |
|---|---|---|
| `card_products` | id, type(credit/debit), name, description, active | |
| `cards` | id, member_id, product_id FK, name, type, number_last4, expiry, status(active/suspended/lost/terminated), issued_at, payment_account_id, payment_bank_name, payment_account_masked, payment_day(1~28), credit_limit, debit_per_tx, debit_per_day, suspended_at, lost_at, lost_reason, terminated_at, terminated_reason | 종류별 필수/금지 컬럼 CHECK, `UNIQUE(member_id, number_last4)`, `INDEX(member_id, status)` |
| `card_status_history` | id, card_id FK, member_id, action, from_status, to_status, occurred_at, request_id | 상태 변경과 같은 트랜잭션 |
| `card_transactions` | id, card_id FK, kind(approval/cancel), occurred_at, merchant, amount>0, installment_months(0 또는 2~12), original_id FK(self) | `UNIQUE(original_id)`, `INDEX(card_id, occurred_at DESC, id DESC)` |
| `card_applications` | id, member_id, type, product_id, payment_account_id, payment_day, income_range, recipient, phone, address_line1/2, agree_*, status(approved/rejected), reject_reason, granted_limit, result_card_id, requested_at | PIN 저장 안 함, 거절 건 90일 뒤 개인정보 비움 |
| `card_issue_quota` | PK(member_id, type) | 행 락 전용 |

## 5. 가계부 (박의혁) — 기획안 4절을 카드 모델에 맞춰 정리

### 5.1 기획안 초안과 달라진 점 (충돌 정리)

| 기획안 초안 | 통합안 | 이유 |
|---|---|---|
| `users` | `members` | 카드·계좌와 같은 회원 테이블 사용 |
| `accounts` | 3절 `accounts` 재사용 | 중복 방지, 대표계좌는 `is_primary` |
| `card_transactions`(user_id, category, approved_at, status, refund_of) | **카드 도메인 `card_transactions` 재사용** (취소 = `kind='cancel'` + `original_id`) + `ledger_tx_category` 분리 | 거래 원장은 카드가 소유. 가계부는 읽기 + 분류만 추가 |
| 거래 `status`(승인/거절/환불) | 거절은 `payment_attempts`로, 환불은 `cancel` 행으로 | 카드 거래에는 승인·취소만 존재 |
| `payment_attempts` | 유지 | 모의 결제 보류 근거 기록 |

### 5.2 테이블

**`ledger_tx_category`** — 카드 거래 분류 (사용자가 변경 가능)
`card_transaction_id` PK/FK → card_transactions · `member_id` · `category` VARCHAR(20) (`food`/`delivery`/`transport`/…) · `source` (`auto`/`user`) · `updated_at`. 인덱스 `(member_id, category)`.

**`budgets`** — 월 예산
`id` · `member_id` · `month` CHAR(7) `YYYY-MM` · `total_amount` BIGINT · `emergency_floor` BIGINT(최소 잔액) · `created_at`/`updated_at`. `UNIQUE (member_id, month)`.

**`category_budgets`**
`budget_id` FK · `category` · `amount` BIGINT. PK `(budget_id, category)`.

**`planned_outflows`** — 예정 출금 (카드대금·고정비)
`id` · `member_id` · `due_date` · `amount` · `type`(`card_bill`/`fixed`/`loan_repayment`) · `ref_type`/`ref_id`(카드 결제일 묶음·대출 상환일정 연결) · `status`(`planned`/`done`/`canceled`).

**`payment_attempts`** — 결제 전 확인(모의) 기록
`id` · `member_id` · `amount` · `category` · `result`(`allowed`/`held`) · `reason`(`MONTH_BUDGET`/`CATEGORY_BUDGET`/`BALANCE`) · `over_amount` · `card_transaction_id` NULL(허용 후 승인된 경우) · `created_at`. 인덱스 `(member_id, created_at)`.

**`ledger_settings`** — 말투 모드 저장
`member_id` PK · `mode`(`roast`/`basic`/`kind`/`numbers`) · `roast_level` SMALLINT · `updated_at`.

**`chat_sessions`** · **`chat_messages`**
세션: `id`, `member_id`, `created_at`. 메시지: `id`, `session_id` FK, `role`(`user`/`assistant`), `content`, `intent`, `context_json` JSONB, `created_at`. 사용자별 대화 분리.

**`rag_documents`** — 상품·이용 안내 검색용
`id` · `source_url` · `title` · `version` · `chunk_text` · `embedding`(pgvector 쓸 경우 `vector`) · `effective_date`. 출처·기준일 답변용.

> 집계(월 순지출, 남은 예산, 결제 후 예상 잔액)는 **테이블에 저장하지 않고 조회 시 계산**한다 (기획안 "서버에서 다시 계산" 원칙).

## 6. 대출 (임대진)

대출 기획서의 공통 테이블만 정리했다(정부·기관·대환·대출관리 업무별 확장 테이블은 제외). 원문은 `feature/loan`의 `일반대출_기획서 6장`, `Loan_Service_main 13.1`.

### 6.1 공통 테이블

| 테이블 | 주요 컬럼 | 설명 |
|---|---|---|
| `loan_application` | id, **member_id**, product_type, status, channel, created_at, expires_at | 신청서 (원문 `customer_id` → `member_id`) |
| `consent_record` | application_id, consent_code, doc_version_hash, agreed, agreed_at, ip | 동의 이력 |
| `applicant_profile` | application_id, job_type, annual_income, debts, purpose_code, prefs JSONB | 고객정보확인서 |
| `suitability_result` | application_id, result, reason_codes, rule_version | 적합성 판정 |
| `evidence` | id, application_id, doc_type, source(API/UPLOAD), extracted JSONB, confidence JSONB, mismatch_flags | 증빙 |
| `review_result` | application_id, result_code, approved_limit, grade, dsr, conditions, reason_codes, rule_version, reviewer_id | 심사 결과 |
| `product_catalog` | product_id, type, name, rules JSONB, rate_rule_id, sale_from, sale_to, version | 상품 |
| `reg_param` | key, value, effective_from, version | 규제값 (DSR·LTV·스트레스 금리) |
| `recommendation_log` | application_id, 후보, 제외 사유, 점수, 버전, LLM 출력, 검증 결과 | 추천·검증 |
| `loan_terms` | application_id, 금액, 기간, 상환방식 | 조건 |
| `pricing` | application_id, 금리 구성(기준금리·가산금리·우대) | 금리 확정 |
| `repayment_schedule` | contract_no, seq, due_date, principal, interest, balance | 상환 스케줄 |
| `explanation_record` | application_id, doc_id, read_seconds, scrolled, quiz_results | 설명의무 |
| `contract` | contract_no, application_id, signed_at, doc_hash | 약정 |
| `collateral` | contract_no, type, detail JSONB, registered_at | 담보 |
| `disbursement` | contract_no, payee, **account_id**, amount, executed_at, result | 지급 |
| `audit_log` | 3절 공용 사용 | |

공통 추가(main 13.1): `inquiry_log`(출처·시각·해시), `inquiry_cache`, `rule_version`, `reason_code`, `llm_call_log`, `prompt_registry`, `document_store`, `saga_instance`, `notification`.

### 6.2 대출 쪽 보완 제안 (원문에 없는 부분)

- 원문에 PK/FK/타입이 없다. `loan_application.id`는 `loan_…` ULID, `contract_no`는 업무용 번호(예 `LN-2026-000123`)로 `UNIQUE`를 걸고, 하위 테이블은 `contract_no` FK.
- 대출 도메인에서 쓰는 금액은 모두 `BIGINT`(원), 금리는 `NUMERIC(6,4)`, JSON 컬럼은 `JSONB`.
- 대출 지급·상환은 `accounts`/`account_transactions`와 연결(`disbursement.account_id`, `account_transactions.ref_id`). 이게 없으면 계좌 잔액과 대출 실행이 따로 논다.
- 가계부 `planned_outflows`가 `repayment_schedule`의 다음 회차를 읽도록 연결하면 "상환일 반영 후 예상 잔액"이 계산된다.

## 7. 도메인 간 연결 키

| 연결 | 방식 |
|---|---|
| 카드 ↔ 계좌 | `cards.payment_account_id` → `accounts.id` (논리), 은행명·마스킹은 스냅샷 |
| 가계부 ↔ 카드 | `ledger_tx_category.card_transaction_id` FK, 청구 묶음은 카드 03 계산 결과를 `planned_outflows`로 반영 |
| 가계부 ↔ 대출 | `planned_outflows.ref_type='loan_repayment'`, `ref_id=repayment_schedule` |
| 대출 ↔ 계좌 | `disbursement.account_id`, `account_transactions.ref_id` |
| 전 도메인 ↔ 회원 | `member_id` (논리 참조), 토큰에서 추출한 값만 사용 (본문 값 불신) |

## 8. 팀 합의가 필요한 항목

1. **로그인·회원 담당** 확정 (`roles.md`에 없음) — `members` 테이블 소유자.
2. **일반 계좌(김연준)** 테이블 확정 — 3절은 카드 명세에서 역산한 제안일 뿐.
3. 용어 통일: 대출 `customer_id`, 가계부 `user_id` → **`member_id`**.
4. 거래 원장 소유: 카드가 `card_transactions` 소유, 가계부는 읽기 전용 + `ledger_tx_category`만 추가 (5.1).
5. 가계부 거래 `status`(승인/거절/환불) vs 카드 `kind`(approval/cancel) — 5.1 방식(거절은 `payment_attempts`) 동의 여부.
6. 대출 도메인에 PK/FK/타입/인덱스 구체화 (6.3) — 임대진.
7. 개인정보 보관 기간: 카드는 거절 신청 90일 제안, 대출은 법정 보존 기간이라 도메인별로 다름.
