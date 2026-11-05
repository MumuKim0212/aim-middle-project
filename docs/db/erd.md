# ERD (Mermaid)

기획 문서의 DB 설계를 ERD로 그린 것이다. 기준 문서는 [회원,인증.md 8장](../auth/회원,인증.md), [계좌.md 7장](../account/계좌.md), [카드 backend-spec 2장](../dev/card/backend-spec.md), [공통.md 6·7장](../common/공통.md)이고, 가계부·대출은 [db-design.md](db-design.md)를 따른다. [db-design.md](db-design.md)도 같은 기준으로 정렬했다. 다르면 기획 문서가 정본이다.
실선(`--`)은 FK, 점선(`..`)은 **도메인 간 논리 참조**(FK 없음)다.
GitHub·VS Code(Mermaid 미리보기)·Notion 코드블록(Mermaid)에서 바로 렌더링된다. 컬럼은 키와 핵심 컬럼만 적었다. 전체 컬럼은 각 기획 문서의 표가 정본이고, 구현은 `backend/app/models.py`다.

규칙 (공통.md 6장): 회원·계좌 ID는 `BIGINT IDENTITY`(시드 id를 고정하는 users, products, accounts는 BY DEFAULT), 금액은 `BIGINT`(원), 시각은 `TIMESTAMPTZ`. 회원 테이블은 `users`이고 다른 테이블의 `user_id`는 모두 `BIGINT`다.

## 1. 전체 관계도 (테이블 단위)

```mermaid
erDiagram
    %% ── 회원 · 인증 ──
    users ||--o{ devices : "기기 등록"

    %% ── 계좌 ──
    users ||--o{ accounts : "소유"
    users ||--o{ favorite_accounts : "자주 쓰는 계좌"
    products ||--o{ accounts : "상품"
    accounts ||--o{ transactions : "입출금"
    accounts }o--o| accounts : "linked_account_id (예적금 → 저축예금)"
    transactions }o--o| accounts : "counterparty_account_id"

    %% ── 카드 ──
    card_products ||--o{ cards : "상품"
    cards ||--o{ card_status_history : "상태 이력"
    cards ||--o{ card_transactions : "거래"
    card_transactions |o--o| card_transactions : "취소 → 원 승인"
    card_products ||--o{ card_applications : "신청 상품"
    card_applications }o--o| cards : "result_card_id"

    users ||..o{ cards : "user_id"
    users ||..o{ card_applications : "user_id"
    accounts ||..o{ cards : "payment_account_id"
    accounts ||..o{ card_applications : "payment_account_id"

    %% ── 가계부 ──
    card_transactions ||--o| ledger_tx_category : "분류"
    budgets ||--o{ category_budgets : "카테고리 예산"
    chat_sessions ||--o{ chat_messages : "대화"
    card_transactions |o--o{ payment_attempts : "허용된 시도"

    users ||..o{ budgets : "user_id"
    users ||..o{ planned_outflows : "user_id"
    users ||..o{ payment_attempts : "user_id"
    users ||..|| ledger_settings : "user_id"
    users ||..o{ ledger_goals : "user_id"
    users ||..o{ chat_sessions : "user_id"
    users ||..o{ ledger_tx_category : "user_id"

    %% ── 대출 (공통) ──
    users ||..o{ loan_application : "user_id"
    loan_application ||--o{ consent_record : "동의"
    loan_application ||--o| applicant_profile : "고객정보"
    loan_application ||--o| suitability_result : "적합성"
    loan_application ||--o{ evidence : "증빙"
    loan_application ||--o| review_result : "심사"
    loan_application ||--o{ recommendation_log : "추천"
    loan_application ||--o| loan_terms : "조건"
    loan_application ||--o| pricing : "금리"
    loan_application ||--o{ explanation_record : "설명의무"
    loan_application ||--o| contract : "약정"
    product_catalog ||--o{ loan_terms : "상품"
    contract ||--o{ repayment_schedule : "상환 스케줄"
    contract ||--o{ collateral : "담보"
    contract ||--o{ disbursement : "지급"
    accounts ||..o{ disbursement : "account_id"
    repayment_schedule ||..o{ planned_outflows : "loan_repayment 연결"
    transactions }o..o| disbursement : "ref_id"
```

## 2. 도메인별 상세 (컬럼 포함)

### 2.1 회원 · 인증 · 계좌

```mermaid
erDiagram
    users {
        bigint id PK "BY DEFAULT (시드 1~4 고정)"
        varchar20 login_id UK "소문자 정규화"
        text password_hash "bcrypt"
        varchar30 name
        date birth_date
        varchar11 phone "숫자만"
        boolean marketing_agree
        text simple_pin_hash "6자리, 미설정이면 NULL"
        timestamptz pin_set_at
        int pin_failed_count
        timestamptz pin_locked_until "재설정으로만 해제"
        int failed_login_count
        timestamptz locked_until "10분 잠금"
        timestamptz created_at
        timestamptz last_login_at
    }
    devices {
        bigint id PK
        bigint user_id FK
        text token_hash UK "SHA-256"
        text device_name
        timestamptz created_at
        timestamptz last_used_at
        timestamptz expires_at "90일 슬라이딩"
        timestamptz revoked_at
    }
    products {
        bigint id PK "BY DEFAULT (1 저축예금, 2 정기예금, 3 정기적금)"
        text type "checking|deposit|savings"
        text name
        text description
        numeric52 rate
        numeric52 early_close_rate
        bigint min_amount
        bigint max_amount
        int min_months
        int max_months
        int max_per_user
        boolean requires_checking
    }
    accounts {
        bigint id PK "BY DEFAULT (시드 1~6 고정)"
        bigint user_id FK
        bigint product_id FK
        text account_no UK "1002-XXX-XXXXXX"
        text alias
        bigint balance
        numeric52 rate "개설 시점 확정"
        int term_months "예적금"
        bigint monthly_amount "적금"
        int payment_day "적금"
        int paid_count "적금"
        boolean auto_pay "적금, 기본 true"
        bigint linked_account_id FK "예적금의 지정 저축예금"
        date opened_at
        date maturity_date
        text status "active|matured|closed_early|closed"
        timestamptz closed_at
        boolean is_primary "저축예금만"
    }
    transactions {
        bigint id PK
        bigint account_id FK
        text type "open|deposit|transfer_in|transfer_out|interest|close (card_payment 예약)"
        bigint amount
        bigint balance_after
        bigint counterparty_account_id FK
        text counterparty_name
        text memo
        timestamptz created_at
    }
    favorite_accounts {
        bigint id PK
        bigint user_id FK
        text account_no
        text display_name
        timestamptz created_at
    }
    idempotency_keys {
        bigint user_id PK
        varchar36 idem_key PK
        char64 fingerprint
        smallint response_status
        text response_body
        timestamptz expires_at
    }
    audit_log {
        varchar40 id PK
        varchar40 entity
        varchar40 entity_id
        varchar30 action
        json before
        json after
        varchar40 actor
        timestamptz at
    }
    users ||--o{ devices : "기기 등록"
    users ||--o{ accounts : owns
    users ||--o{ favorite_accounts : has
    products ||--o{ accounts : "상품"
    accounts ||--o{ transactions : has
    accounts }o--o| accounts : "linked_account_id"
```

- 계좌 비밀번호(`account_pin_state`)는 없다. 본인 재확인은 간편비밀번호 6자리(`users.simple_pin_hash`)이고 틀린 횟수는 `users.pin_failed_count`가 센다 (공통.md 4장).
- 거래 테이블 이름은 계좌.md 기준 `transactions`다 (예전 설계의 `account_transactions`). 카드 거래는 `card_transactions`로 따로 둔다.
- 세션은 서명 쿠키라 세션 테이블이 없다 (회원,인증.md 8.3).

### 2.2 카드

```mermaid
erDiagram
    card_products {
        varchar40 id PK
        varchar6 type "credit|debit"
        varchar50 name
        varchar200 description
        boolean active
    }
    cards {
        varchar40 id PK
        bigint user_id "논리 참조"
        varchar40 product_id FK
        varchar50 name
        varchar6 type
        char4 number_last4 "UK(user_id,number_last4)"
        char5 expiry
        varchar12 status "active|suspended|lost|terminated"
        date issued_at
        bigint payment_account_id "논리 참조"
        varchar30 payment_bank_name "스냅샷"
        varchar20 payment_account_masked "스냅샷"
        smallint payment_day "신용만"
        bigint credit_limit "신용만"
        bigint debit_per_tx "체크만"
        bigint debit_per_day "체크만"
        timestamptz suspended_at
        timestamptz lost_at
        varchar6 lost_reason "lost|stolen"
        timestamptz terminated_at
        varchar30 terminated_reason "응답에 없음"
    }
    card_status_history {
        varchar40 id PK
        varchar40 card_id FK
        bigint user_id
        varchar12 action
        varchar12 from_status
        varchar12 to_status
        timestamptz occurred_at
    }
    card_transactions {
        varchar40 id PK
        varchar40 card_id FK
        varchar8 kind "approval|cancel"
        timestamptz occurred_at
        varchar100 merchant
        bigint amount
        smallint installment_months
        varchar40 original_id FK "UK, 취소일 때 원 승인"
    }
    card_applications {
        varchar40 id PK
        bigint user_id
        varchar6 type
        varchar40 product_id FK
        bigint payment_account_id
        varchar10 income_range
        varchar8 status "approved|rejected"
        bigint granted_limit
        varchar40 result_card_id FK
        timestamptz requested_at
    }
    card_issue_quota {
        bigint user_id PK
        varchar6 type PK
    }
    card_products ||--o{ cards : has
    cards ||--o{ card_status_history : logs
    cards ||--o{ card_transactions : has
    card_transactions |o--o| card_transactions : cancels
    card_products ||--o{ card_applications : applied
    card_applications }o--o| cards : issues
```

### 2.3 가계부

```mermaid
erDiagram
    card_transactions {
        varchar40 id PK
    }
    ledger_tx_category {
        varchar40 card_transaction_id PK
        bigint user_id
        varchar20 category
        varchar4 source "auto|user"
    }
    budgets {
        varchar40 id PK
        bigint user_id "UK(user_id,month)"
        char7 month "YYYY-MM"
        bigint total_amount
        bigint emergency_floor
    }
    category_budgets {
        varchar40 budget_id PK
        varchar20 category PK
        bigint amount
    }
    planned_outflows {
        varchar40 id PK
        bigint user_id
        date due_date
        bigint amount
        varchar20 type "card_bill|fixed|loan_repayment"
        varchar20 ref_type
        varchar40 ref_id
        varchar10 status
    }
    payment_attempts {
        varchar40 id PK
        bigint user_id
        bigint amount
        varchar20 category
        varchar8 result "allowed|held"
        varchar20 reason "MONTH_BUDGET|CATEGORY_BUDGET|BALANCE"
        bigint over_amount
        varchar40 card_transaction_id FK
    }
    ledger_settings {
        bigint user_id PK
        varchar8 mode "roast|basic|kind|numbers"
        smallint roast_level
    }
    ledger_goals {
        varchar40 id PK
        bigint user_id
        varchar7 month "YYYY-MM, 회원당 월 1건"
        varchar30 name
        bigint target_amount
    }
    chat_sessions {
        varchar40 id PK
        bigint user_id
    }
    chat_messages {
        varchar40 id PK
        varchar40 session_id FK
        varchar10 role
        text content
        varchar30 intent
        json context_json
    }
    rag_documents {
        varchar40 id PK
        varchar300 source_url
        varchar200 title
        varchar20 version
        text chunk_text
        vector768 embedding "pgvector"
        date effective_date
    }
    card_transactions ||--o| ledger_tx_category : classified
    card_transactions |o--o{ payment_attempts : approved
    budgets ||--o{ category_budgets : has
    chat_sessions ||--o{ chat_messages : has
```

### 2.4 대출 (공통 테이블)

```mermaid
erDiagram
    loan_application {
        varchar40 id PK
        bigint user_id "논리 참조"
        varchar20 product_type
        varchar20 status
        varchar10 channel
        timestamptz expires_at
    }
    consent_record {
        varchar40 id PK
        varchar40 application_id FK
        varchar30 consent_code
        char64 doc_version_hash
        boolean agreed
        timestamptz agreed_at
    }
    applicant_profile {
        varchar40 application_id PK
        varchar20 job_type
        bigint annual_income
        bigint debts
        varchar20 purpose_code
        json prefs
    }
    suitability_result {
        varchar40 application_id PK
        varchar20 result
        json reason_codes
        varchar20 rule_version
    }
    evidence {
        varchar40 id PK
        varchar40 application_id FK
        varchar30 doc_type
        varchar6 source "API|UPLOAD"
        json extracted
        json confidence
    }
    review_result {
        varchar40 application_id PK
        varchar20 result_code
        bigint approved_limit
        varchar10 grade
        numeric dsr
        varchar40 reviewer_id
    }
    product_catalog {
        varchar40 product_id PK
        varchar20 type
        varchar100 name
        json rules
        date sale_from
        date sale_to
        int version
    }
    reg_param {
        varchar40 key PK
        int version PK
        varchar100 value
        date effective_from
    }
    recommendation_log {
        varchar40 id PK
        varchar40 application_id FK
        json candidates
        json excluded_reasons
        json llm_output
        json validation
    }
    loan_terms {
        varchar40 application_id PK
        varchar40 product_id FK
        bigint amount
        smallint term_months
        varchar20 repay_method
    }
    pricing {
        varchar40 application_id PK
        numeric base_rate
        numeric spread
        numeric preferential
        numeric final_rate
    }
    explanation_record {
        varchar40 id PK
        varchar40 application_id FK
        varchar40 doc_id
        int read_seconds
        boolean scrolled
    }
    contract {
        varchar30 contract_no PK
        varchar40 application_id FK "UK"
        timestamptz signed_at
        char64 doc_hash
    }
    repayment_schedule {
        varchar30 contract_no PK
        int seq PK
        date due_date
        bigint principal
        bigint interest
        bigint balance "납부 후 잔액"
    }
    collateral {
        varchar40 id PK
        varchar30 contract_no FK
        varchar20 type
        json detail
    }
    disbursement {
        varchar40 id PK
        varchar30 contract_no FK
        varchar50 payee
        bigint account_id "논리 참조 accounts"
        bigint amount
        timestamptz executed_at
        varchar10 result
    }
    loan_application ||--o{ consent_record : has
    loan_application ||--o| applicant_profile : has
    loan_application ||--o| suitability_result : has
    loan_application ||--o{ evidence : has
    loan_application ||--o| review_result : has
    loan_application ||--o{ recommendation_log : has
    loan_application ||--o| loan_terms : has
    loan_application ||--o| pricing : has
    loan_application ||--o{ explanation_record : has
    loan_application ||--o| contract : signs
    product_catalog ||--o{ loan_terms : selected
    contract ||--o{ repayment_schedule : has
    contract ||--o{ collateral : has
    contract ||--o{ disbursement : pays
```

## 3. 참고

- `chat_sessions`·`chat_messages`는 구현된 가계부 대화가 쓰는 테이블이고 홈 자연어 입력창도 같은 테이블을 쓴다 (공통.md 9.3).
- 카드의 `payment_account_id`는 FK 없는 논리 참조다 (카드 backend-spec). 결제 계좌 후보는 저축예금이고 active인 계좌만이다.
- 대출 쪽 `inquiry_log`, `rule_version`, `llm_call_log`, `saga_instance`, `notification` 등 main 13.1의 "공통 추가" 테이블은 스켈레톤 단계라 모델·ERD에서 뺐다.
- 업무별 확장 테이블(정부·기관·대환·대출관리)은 설계에서 제외했다.
