-- [역할] 대출 서비스 전체 DB 스키마(DDL). SQLite로 바로 실행되고 PostgreSQL로 옮기기 쉬운 형태로 작성.
--
-- 작성 규칙 (팀 공통 규칙 docs/db/db-design.md 1절 준수)
--   · 금액 BIGINT(원), 금리 NUMERIC(6,4)(연 %, 예: 4.8500), 비율 NUMERIC(8,4)
--   · ID: VARCHAR(40) 접두어 + ULID (예: lap_01J...). 계약 번호는 업무 번호(LA-2026-000123, 대환 RA-...)
--   · enum은 VARCHAR + CHECK, JSON은 JSONB(SQLite에서는 텍스트로 저장)
--   · 같은 도메인 안은 FK, 다른 서비스(회원·로그인·은행·카드)는 FK 없이 "논리 참조" 빈 칸으로 둠
--
-- 주석 태그 (tools/make_erd.py가 읽어 ERD를 그림)
--   @domain <이름>      : 테이블이 속한 영역
--   @ext <서비스>       : 아직 만들지 않은 외부 서비스와 연결할 빈 칸(NULL 허용, FK 없음)
--
-- 외부 서비스 (아직 테이블 없음 → 통합할 때 FK 또는 API로 연결)
--   회원·개인정보 : users.id              ← user_id, spouse_user_id (BIGINT)
--   로그인·인증   : auth_session/sign 참조 ← auth_ref, signature_ref
--   은행(계좌)    : accounts.id, transactions.id ← account_id, debit_account_id, auto_debit_account_id, account_txn_ref (BIGINT)
--   카드          : cards.id               ← card_id (우대금리 카드 실적)
--   메인 화면     : loan_account·product_catalog를 읽어 요약 표시 (테이블 연결 없음, 조회 API)

PRAGMA foreign_keys = ON;

-- =====================================================================
-- @domain 기준정보 (상품·규제·규칙·코드)
-- =====================================================================

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS product_catalog (
    product_id      VARCHAR(20)  PRIMARY KEY,                 -- 예: g1, p1, i1, r1
    business_type   VARCHAR(10)  NOT NULL CHECK (business_type IN ('GENERAL','POLICY','INST','REFI')),
    inst_kind       VARCHAR(1)   CHECK (inst_kind IN ('A','B')),   -- 기관대출: A 보증부, B 협약
    collateral_type VARCHAR(10)  NOT NULL CHECK (collateral_type IN ('CREDIT','JEONSE','MORTGAGE','AUTO','DEPOSIT')),
    name            VARCHAR(80)  NOT NULL,
    subtitle        VARCHAR(80)  NOT NULL,
    target_desc     VARCHAR(200) NOT NULL,
    max_amount      BIGINT       NOT NULL CHECK (max_amount > 0),
    min_amount      BIGINT       NOT NULL CHECK (min_amount > 0),
    rate_min        NUMERIC(6,4) NOT NULL,
    rate_max        NUMERIC(6,4) NOT NULL,
    term_options    JSONB        NOT NULL,                    -- [12,24,36]
    repay_options   JSONB        NOT NULL,                    -- ["원리금균등분할", ...]
    rules           JSONB,                                    -- 상품별 추가 규칙
    sale_from       DATE         NOT NULL,
    sale_to         DATE,
    version         INTEGER      NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ  NOT NULL,
    CHECK (min_amount <= max_amount),
    CHECK (rate_min <= rate_max)
);

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS reg_param (
    param_key       VARCHAR(40)  NOT NULL,                    -- DSR_LIMIT, STRESS_ADD, LTV_LIMIT ...
    version         INTEGER      NOT NULL,
    value           NUMERIC(14,4) NOT NULL,
    unit            VARCHAR(10)  NOT NULL,                    -- ratio, %p, won, months
    description     VARCHAR(200) NOT NULL,
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    approved_by     VARCHAR(40)  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (param_key, version)
);

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS rule_version (
    rule_id         VARCHAR(40)  NOT NULL,                    -- SUIT-RULE, REFI-ELIG, RATE-RULE ...
    version         INTEGER      NOT NULL,
    rule_type       VARCHAR(20)  NOT NULL,
    body            JSONB        NOT NULL,
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    approved_by     VARCHAR(40)  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (rule_id, version)
);

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS reason_code (
    code            VARCHAR(40)  PRIMARY KEY,                 -- KO-DELINQ-CURRENT ...
    code_group      VARCHAR(20)  NOT NULL,                    -- DOC, CON, SUIT, KO, INC, CRD, DSR, COL, POL, GUA, ORG, REFI
    message         VARCHAR(200) NOT NULL,
    fixable         BOOLEAN      NOT NULL                     -- 서류 보완으로 해결 가능한 코드인지
);

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS form_template (
    form_no         VARCHAR(10)  PRIMARY KEY,                 -- LN-01 ~ LN-28, RF-01 ~ RF-19
    service         VARCHAR(4)   NOT NULL CHECK (service IN ('LOAN','REFI')),
    title           VARCHAR(120) NOT NULL,
    file_name       VARCHAR(200) NOT NULL,
    version_hash    VARCHAR(64)  NOT NULL                     -- 동의 당시 문서 버전 고정용
);

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS consent_code (
    code            VARCHAR(30)  PRIMARY KEY,                 -- TERMS_BASIC, CREDIT_INQUIRY, MYDATA_TRANSFER ...
    title           VARCHAR(120) NOT NULL,
    required_for    VARCHAR(40)  NOT NULL,                    -- ALL, POLICY, INST_A, INST_B, REFI, OPTIONAL
    form_no         VARCHAR(10)  REFERENCES form_template(form_no)
);

-- @domain 기준정보
CREATE TABLE IF NOT EXISTS prompt_registry (
    use_case_id     VARCHAR(20)  NOT NULL,                    -- LLM-1 ~ LLM-8, GLLM-*, ILLM-*, RLLM-*, MLLM-*
    version         INTEGER      NOT NULL,
    model_tier      VARCHAR(10)  NOT NULL CHECK (model_tier IN ('light','standard','high')),
    template        TEXT         NOT NULL,
    output_schema   JSONB        NOT NULL,
    timeout_ms      INTEGER      NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (use_case_id, version)
);

-- =====================================================================
-- @domain 신청·심사 (C01~C06)
-- =====================================================================

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS loan_application (
    application_id  VARCHAR(40)  PRIMARY KEY,                 -- lap_<ULID>
    user_id         BIGINT,                                   -- @ext 회원·개인정보 (users.id) — 통합 전에는 비워 둠
    auth_ref        VARCHAR(64),                              -- @ext 로그인·인증 (본인인증 세션 참조)
    product_id      VARCHAR(20)  NOT NULL REFERENCES product_catalog(product_id),
    business_type   VARCHAR(10)  NOT NULL CHECK (business_type IN ('GENERAL','POLICY','INST','REFI')),
    status          VARCHAR(30)  NOT NULL,                    -- 3장 상태 머신 (DRAFT ... COMPLETED)
    channel         VARCHAR(10)  NOT NULL CHECK (channel IN ('WEB','APP','CLI')),
    scenario_key    VARCHAR(20),                              -- 체험 고객 키(데모 전용, 통합 시 제거)
    created_at      TIMESTAMPTZ  NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL,
    expires_at      TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_app_user ON loan_application(user_id);
CREATE INDEX IF NOT EXISTS ix_app_status ON loan_application(status);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS application_status_history (
    history_id      VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    from_status     VARCHAR(30),
    to_status       VARCHAR(30)  NOT NULL,
    step_code       VARCHAR(10),                              -- C01~C14
    actor           VARCHAR(40)  NOT NULL,                    -- system / customer / reviewer
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS consent_record (
    consent_id      VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    consent_code    VARCHAR(30)  NOT NULL REFERENCES consent_code(code),
    agreed          BOOLEAN      NOT NULL,
    doc_version_hash VARCHAR(64) NOT NULL,
    auth_ref        VARCHAR(64),                              -- @ext 로그인·인증 (동의 시 인증 참조)
    agreed_at       TIMESTAMPTZ  NOT NULL,
    withdrawn_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_consent_app ON consent_record(application_id, consent_code);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS applicant_profile (
    application_id  VARCHAR(40)  PRIMARY KEY REFERENCES loan_application(application_id),
    job_type        VARCHAR(10)  NOT NULL CHECK (job_type IN ('급여소득자','개인사업자','프리랜서','연금소득자')),
    employer_name   VARCHAR(80),
    tenure_months   INTEGER      NOT NULL CHECK (tenure_months >= 0),
    annual_income   BIGINT       NOT NULL CHECK (annual_income >= 0),
    assets          BIGINT       NOT NULL CHECK (assets >= 0),
    debt_monthly    BIGINT       NOT NULL CHECK (debt_monthly >= 0),
    delinquent_1y   BOOLEAN      NOT NULL,
    purpose_code    VARCHAR(20)  NOT NULL,
    desired_amount  BIGINT       NOT NULL CHECK (desired_amount >= 0),
    desired_term    INTEGER      NOT NULL CHECK (desired_term > 0),
    repay_method    VARCHAR(10)  NOT NULL CHECK (repay_method IN ('원리금균등분할','만기일시상환','원금균등분할')),
    rate_pref       VARCHAR(10)  NOT NULL CHECK (rate_pref IN ('고정금리','변동금리','혼합형','상관없음')),
    collateral      JSONB,                                    -- 보증금·시세·선순위·차량가·예금 잔액
    credit_score    INTEGER,                                  -- CB 조회 결과(데모는 시나리오 값)
    updated_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS suitability_result (
    suitability_id  VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    result          VARCHAR(12)  NOT NULL CHECK (result IN ('SUITABLE','WARNING','UNSUITABLE')),
    burden_ratio    NUMERIC(8,4) NOT NULL,
    reason_codes    JSONB        NOT NULL,
    rule_version    VARCHAR(30)  NOT NULL,
    override        BOOLEAN      NOT NULL DEFAULT 0,          -- 고지 확인 후 진행(suitability_override)
    override_notice VARCHAR(40),
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS inquiry_log (
    inquiry_id      VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    source          VARCHAR(20)  NOT NULL,                    -- CB, PUBLIC, MYDATA, PRICE, REGISTRY, GUARANTOR, ORG, AGENCY, REFI_INFRA
    purpose         VARCHAR(40)  NOT NULL,
    consent_codes   JSONB        NOT NULL,                    -- 동의 게이트를 통과한 근거
    request_hash    VARCHAR(64)  NOT NULL,
    response_hash   VARCHAR(64),
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('OK','BLOCKED','FAILED','CACHED')),
    fetched_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS inquiry_cache (
    cache_key       VARCHAR(64)  PRIMARY KEY,                 -- hash(user, source, query)
    user_id         BIGINT,                                   -- @ext 회원·개인정보
    source          VARCHAR(20)  NOT NULL,
    payload_masked  JSONB        NOT NULL,                    -- 마스킹된 결과만 저장
    fetched_at      TIMESTAMPTZ  NOT NULL,
    expires_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    doc_key         VARCHAR(20)  NOT NULL,                    -- income, emp, hi, lease, reg, sale, car, family, bal
    doc_type        VARCHAR(60)  NOT NULL,
    source          VARCHAR(10)  NOT NULL CHECK (source IN ('API','UPLOAD','DEMO')),
    file_name       VARCHAR(200),
    file_size       BIGINT,
    file_sha256     VARCHAR(64),
    extracted       JSONB,                                    -- LLM-3 추출 결과(마스킹)
    confidence      JSONB,
    defect_codes    JSONB        NOT NULL,
    status          VARCHAR(10)  NOT NULL CHECK (status IN ('OK','DEFECT','INVALID')),
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS review_result (
    review_id       VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    result_code     VARCHAR(16)  NOT NULL CHECK (result_code IN ('APPROVED','COND_APPROVED','DOCS_REQUIRED','REJECTED')),
    approved_limit  BIGINT       NOT NULL CHECK (approved_limit >= 0),
    est_rate        NUMERIC(6,4) NOT NULL,
    dsr             NUMERIC(8,4) NOT NULL,
    credit_score    INTEGER      NOT NULL,
    hard_codes      JSONB        NOT NULL,
    cond_codes      JSONB        NOT NULL,
    doc_codes       JSONB        NOT NULL,
    stages          JSONB        NOT NULL,                    -- 심사 단계별 결과(재현용)
    rule_version    VARCHAR(30)  NOT NULL,
    reviewer_id     VARCHAR(40),                              -- 수기 심사 시 심사역
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS recommendation_log (
    recommendation_id VARCHAR(40) PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    candidates      JSONB        NOT NULL,
    scores          JSONB        NOT NULL,
    chosen_variant  VARCHAR(30),
    weights_version VARCHAR(20)  NOT NULL,
    llm_call_id     VARCHAR(40)  REFERENCES llm_call_log(call_id),
    validation      JSONB        NOT NULL,                    -- V1~V9 (+GV/IV/RV) 결과
    displayed_text  TEXT,
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 신청·심사
CREATE TABLE IF NOT EXISTS household_info (                  -- 정부대출 세대 정보
    application_id  VARCHAR(40)  PRIMARY KEY REFERENCES loan_application(application_id),
    married         BOOLEAN      NOT NULL,
    homeless        BOOLEAN      NOT NULL,
    household_income BIGINT      NOT NULL,
    net_assets      BIGINT       NOT NULL,
    spouse_user_id  BIGINT,                                   -- @ext 회원·개인정보 (배우자)
    spouse_consent_at TIMESTAMPTZ
);

-- =====================================================================
-- @domain 약정·실행 (C07~C13)
-- =====================================================================

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS loan_terms (
    application_id  VARCHAR(40)  PRIMARY KEY REFERENCES loan_application(application_id),
    amount          BIGINT       NOT NULL CHECK (amount > 0),
    term_months     INTEGER      NOT NULL CHECK (term_months > 0),
    repay_method    VARCHAR(10)  NOT NULL CHECK (repay_method IN ('원리금균등분할','만기일시상환','원금균등분할')),
    payment_day     INTEGER      NOT NULL CHECK (payment_day BETWEEN 1 AND 28),
    auto_debit_account_id BIGINT,                             -- @ext 은행(계좌) accounts.id
    payroll_deduction BOOLEAN    NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS pricing (
    application_id  VARCHAR(40)  PRIMARY KEY REFERENCES loan_application(application_id),
    base_rate       NUMERIC(6,4) NOT NULL,
    spread          NUMERIC(6,4) NOT NULL,
    preferential    NUMERIC(6,4) NOT NULL,
    final_rate      NUMERIC(6,4) NOT NULL CHECK (final_rate > 0 AND final_rate <= 20),
    rate_type       VARCHAR(6)   NOT NULL CHECK (rate_type IN ('고정','변동','혼합')),
    guarantee_fee_rate NUMERIC(6,4),
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS pricing_preference (              -- 우대금리 근거
    preference_id   VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES pricing(application_id),
    pref_code       VARCHAR(20)  NOT NULL CHECK (pref_code IN ('SALARY','AUTO_DEBIT','CARD_USAGE')),
    rate_cut        NUMERIC(6,4) NOT NULL,
    account_id      BIGINT,                                   -- @ext 은행(계좌) 급여 이체 계좌
    card_id         VARCHAR(40),                              -- @ext 카드 cards.id (카드 사용 실적)
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS explanation_record (
    explanation_id  VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    form_no         VARCHAR(10)  NOT NULL REFERENCES form_template(form_no),
    scrolled_to_end BOOLEAN      NOT NULL,
    quiz_results    JSONB        NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS contract (
    contract_no     VARCHAR(20)  PRIMARY KEY,                 -- LA-2026-000123 / RA-2026-000123
    application_id  VARCHAR(40)  NOT NULL UNIQUE REFERENCES loan_application(application_id),
    signed_at       TIMESTAMPTZ  NOT NULL,
    doc_hash        VARCHAR(64)  NOT NULL,
    signature_ref   VARCHAR(64),                              -- @ext 로그인·인증 (전자서명 참조)
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS repayment_schedule (
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    seq             INTEGER      NOT NULL,
    due_date        DATE         NOT NULL,
    principal       BIGINT       NOT NULL,
    interest        BIGINT       NOT NULL,
    balance_after   BIGINT       NOT NULL CHECK (balance_after >= 0),
    PRIMARY KEY (contract_no, seq)                            -- 가계부 planned_outflows가 ref_id로 참조
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS collateral (
    collateral_id   VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    collateral_type VARCHAR(10)  NOT NULL CHECK (collateral_type IN ('MORTGAGE','JEONSE','AUTO','DEPOSIT')),
    detail          JSONB        NOT NULL,
    registration_no VARCHAR(40),
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('SET','RELEASED')),
    registered_at   TIMESTAMPTZ  NOT NULL,
    released_at     TIMESTAMPTZ
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS disbursement (
    disbursement_id VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    payee_type      VARCHAR(12)  NOT NULL CHECK (payee_type IN ('SELF','LANDLORD','SELLER','DEALER','PAYOFF')),
    payee_masked    VARCHAR(80)  NOT NULL,
    account_id      BIGINT,                                   -- @ext 은행(계좌) 지급 계좌 accounts.id
    account_txn_ref BIGINT,                                   -- @ext 은행(계좌) transactions.id
    amount          BIGINT       NOT NULL CHECK (amount > 0),
    result          VARCHAR(10)  NOT NULL CHECK (result IN ('DONE','FAILED','CANCELLED')),
    idempotency_key VARCHAR(80)  NOT NULL UNIQUE,
    executed_at     TIMESTAMPTZ  NOT NULL
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS saga_instance (                   -- 대환 실행·담보 실행 묶음 처리
    saga_id         VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    saga_type       VARCHAR(20)  NOT NULL CHECK (saga_type IN ('REFI_EXECUTE','COLLATERAL_EXECUTE','DISBURSE')),
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('RUNNING','DONE','COMPENSATED','FAILED')),
    steps           JSONB        NOT NULL,
    compensation    JSONB        NOT NULL,
    started_at      TIMESTAMPTZ  NOT NULL,
    finished_at     TIMESTAMPTZ
);

-- @domain 약정·실행
CREATE TABLE IF NOT EXISTS document_store (                  -- 교부·보관 서류
    doc_id          VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    form_no         VARCHAR(10)  NOT NULL REFERENCES form_template(form_no),
    file_hash       VARCHAR(64)  NOT NULL,
    issued_at       TIMESTAMPTZ  NOT NULL
);

-- =====================================================================
-- @domain 정부·기관 확장
-- =====================================================================

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS policy_rule (
    policy_id       VARCHAR(20)  NOT NULL,
    version         INTEGER      NOT NULL,
    product_id      VARCHAR(20)  NOT NULL REFERENCES product_catalog(product_id),
    items           JSONB        NOT NULL,                    -- 자격 기준(소득·자산·무주택)
    rate_table      JSONB        NOT NULL,
    obligations     JSONB        NOT NULL,                    -- 의무 사항 목록
    effective_from  DATE         NOT NULL,
    effective_to    DATE,
    approved_by     VARCHAR(40)  NOT NULL,
    PRIMARY KEY (policy_id, version)
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS policy_check_result (
    check_id        VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    policy_id       VARCHAR(20)  NOT NULL,
    policy_version  INTEGER      NOT NULL,
    item_code       VARCHAR(30)  NOT NULL,
    item_value      VARCHAR(80)  NOT NULL,
    result          VARCHAR(8)   NOT NULL CHECK (result IN ('PASS','FAIL','UNKNOWN')),
    data_source     VARCHAR(20)  NOT NULL,
    checked_at      TIMESTAMPTZ  NOT NULL,
    FOREIGN KEY (policy_id, policy_version) REFERENCES policy_rule(policy_id, version)
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS agency_review (
    agency_review_id VARCHAR(40) PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    agency          VARCHAR(40)  NOT NULL,
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('REQUESTED','APPROVED','REJECTED','SUPPLEMENT')),
    approved_limit  BIGINT,
    requested_at    TIMESTAMPTZ  NOT NULL,
    responded_at    TIMESTAMPTZ
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS agency_report (
    report_id       VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    report_type     VARCHAR(20)  NOT NULL,
    sent_at         TIMESTAMPTZ  NOT NULL,
    ack_at          TIMESTAMPTZ,
    retry_count     INTEGER      NOT NULL DEFAULT 0
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS obligation_check (
    obligation_id   VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    obligation_code VARCHAR(30)  NOT NULL,
    due_date        DATE         NOT NULL,
    result          VARCHAR(10)  NOT NULL CHECK (result IN ('PENDING','PASS','FAIL','EXPLAINED')),
    decided_by      VARCHAR(40),
    decided_at      TIMESTAMPTZ
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS agreement_org (
    org_id          VARCHAR(20)  PRIMARY KEY,
    name            VARCHAR(80)  NOT NULL,
    conditions      JSONB        NOT NULL,                    -- 대상 고용 형태 등
    rate_table      JSONB        NOT NULL,
    total_limit     BIGINT       NOT NULL,
    used_limit      BIGINT       NOT NULL DEFAULT 0,
    valid_from      DATE         NOT NULL,
    valid_to        DATE         NOT NULL,
    CHECK (used_limit <= total_limit)
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS affiliation_check (
    affiliation_id  VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    org_id          VARCHAR(20)  NOT NULL REFERENCES agreement_org(org_id),
    method          VARCHAR(20)  NOT NULL,
    employee_no_hash VARCHAR(64) NOT NULL,                    -- 사번은 해시만 저장
    employment_type VARCHAR(10)  NOT NULL CHECK (employment_type IN ('정규직','계약직')),
    result          VARCHAR(8)   NOT NULL CHECK (result IN ('PASS','FAIL')),
    checked_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS guarantee_rule (
    agency          VARCHAR(10)  NOT NULL,                    -- HUG, HF, SGI (예시)
    version         INTEGER      NOT NULL,
    fee_rate        NUMERIC(6,4) NOT NULL,
    cap_amount      BIGINT       NOT NULL,
    max_ratio       NUMERIC(8,4) NOT NULL,                    -- (선순위+보증금)/시세 상한
    effective_from  DATE         NOT NULL,
    PRIMARY KEY (agency, version)
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS guarantee_request (
    guarantee_id    VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    agency          VARCHAR(10)  NOT NULL,
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('REQUESTED','APPROVED','REJECTED','ISSUED')),
    approved_amount BIGINT,
    fee_rate        NUMERIC(6,4),
    cert_no         VARCHAR(40),
    reason_codes    JSONB        NOT NULL,
    requested_at    TIMESTAMPTZ  NOT NULL,
    issued_at       TIMESTAMPTZ
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS assignment_notice (
    notice_id       VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    landlord_masked VARCHAR(40)  NOT NULL,
    sent_at         TIMESTAMPTZ  NOT NULL,
    confirmed_at    TIMESTAMPTZ
);

-- @domain 정부·기관
CREATE TABLE IF NOT EXISTS org_event (
    org_event_id    VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    org_id          VARCHAR(20)  NOT NULL REFERENCES agreement_org(org_id),
    event_type      VARCHAR(12)  NOT NULL CHECK (event_type IN ('RETIRE','LEAVE','TERMINATE')),
    received_at     TIMESTAMPTZ  NOT NULL,
    action          VARCHAR(20),
    decided_at      TIMESTAMPTZ
);

-- =====================================================================
-- @domain 대환 (R03~R16)
-- =====================================================================

-- @domain 대환
CREATE TABLE IF NOT EXISTS existing_loan (
    existing_loan_id VARCHAR(40) PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    source          VARCHAR(10)  NOT NULL CHECK (source IN ('MYDATA','MANUAL','CB')),
    institution     VARCHAR(60)  NOT NULL,
    kind            VARCHAR(30)  NOT NULL,
    account_masked  VARCHAR(40)  NOT NULL,                    -- 계좌번호 원문은 저장하지 않음
    account_hash    VARCHAR(64)  NOT NULL,
    balance         BIGINT       NOT NULL CHECK (balance >= 0),
    rate            NUMERIC(6,4) NOT NULL,
    since_months    INTEGER      NOT NULL,
    remain_months   INTEGER      NOT NULL,
    total_months    INTEGER      NOT NULL,
    monthly_payment BIGINT       NOT NULL,
    prepay_fee_rate NUMERIC(6,4) NOT NULL,
    is_bullet       BOOLEAN      NOT NULL,
    flags           JSONB        NOT NULL,                    -- delinq, legal, docExpired, assetMismatch
    fetched_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 대환
CREATE TABLE IF NOT EXISTS refi_target (
    refi_target_id  VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    existing_loan_id VARCHAR(40) NOT NULL REFERENCES existing_loan(existing_loan_id),
    eligible        BOOLEAN      NOT NULL,
    reason_codes    JSONB        NOT NULL,
    selected        BOOLEAN      NOT NULL
);

-- @domain 대환
CREATE TABLE IF NOT EXISTS refi_benefit (
    benefit_id      VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    product_id      VARCHAR(20)  NOT NULL REFERENCES product_catalog(product_id),
    new_term        INTEGER      NOT NULL,
    old_remaining_interest BIGINT NOT NULL,
    new_total_interest BIGINT    NOT NULL,
    cost            JSONB        NOT NULL,                    -- 중도상환수수료·인지세
    net_saving      BIGINT       NOT NULL,
    break_even_month INTEGER,
    monthly_change  BIGINT       NOT NULL,
    verdict         VARCHAR(16)  NOT NULL CHECK (verdict IN ('BENEFICIAL','TRADE_OFF','NOT_BENEFICIAL')),
    calc_version    VARCHAR(20)  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 대환
CREATE TABLE IF NOT EXISTS refi_override (
    override_id     VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    verdict         VARCHAR(16)  NOT NULL,
    notice_version  VARCHAR(20)  NOT NULL,
    confirmed_at    TIMESTAMPTZ  NOT NULL
);

-- @domain 대환
CREATE TABLE IF NOT EXISTS payoff_quote (
    quote_id        VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  NOT NULL REFERENCES loan_application(application_id),
    existing_loan_id VARCHAR(40) NOT NULL REFERENCES existing_loan(existing_loan_id),
    principal       BIGINT       NOT NULL,
    interest        BIGINT       NOT NULL,
    prepay_fee      BIGINT       NOT NULL,
    total           BIGINT       NOT NULL,
    valid_until     TIMESTAMPTZ  NOT NULL,
    quoted_at       TIMESTAMPTZ  NOT NULL
);

-- @domain 대환
CREATE TABLE IF NOT EXISTS payoff_record (
    payoff_id       VARCHAR(40)  PRIMARY KEY,
    existing_loan_id VARCHAR(40) NOT NULL REFERENCES existing_loan(existing_loan_id),
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    paid_amount     BIGINT       NOT NULL,
    result          VARCHAR(10)  NOT NULL CHECK (result IN ('PAID_OFF','PARTIAL','FAILED','RETURNED')),
    paid_at         TIMESTAMPTZ  NOT NULL,
    confirmed_at    TIMESTAMPTZ
);

-- @domain 대환
CREATE TABLE IF NOT EXISTS lien_change (
    lien_change_id  VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES contract(contract_no),
    old_lien        JSONB        NOT NULL,
    new_lien        JSONB        NOT NULL,
    released_at     TIMESTAMPTZ,
    registered_at   TIMESTAMPTZ
);

-- =====================================================================
-- @domain 대출관리 (M01~M12)
-- =====================================================================

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS loan_account (
    contract_no     VARCHAR(20)  PRIMARY KEY REFERENCES contract(contract_no),
    user_id         BIGINT,                                   -- @ext 회원·개인정보 (메인 화면 "내 대출" 요약 조회 키)
    account_masked  VARCHAR(40)  NOT NULL,                    -- 대출 계좌번호(마스킹)
    account_hash    VARCHAR(64)  NOT NULL UNIQUE,
    product_id      VARCHAR(20)  NOT NULL REFERENCES product_catalog(product_id),
    status          VARCHAR(12)  NOT NULL CHECK (status IN ('ACTIVE','OVERDUE','ACCELERATED','WITHDRAWN','PAID_OFF','CLOSED')),
    principal       BIGINT       NOT NULL CHECK (principal > 0),
    balance         BIGINT       NOT NULL CHECK (balance >= 0),
    rate            NUMERIC(6,4) NOT NULL,
    term_months     INTEGER      NOT NULL,
    repay_method    VARCHAR(10)  NOT NULL,
    start_date      DATE         NOT NULL,
    next_due_date   DATE,
    debit_account_id BIGINT,                                  -- @ext 은행(계좌) 자동이체 출금 계좌
    updated_at      TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_account_user ON loan_account(user_id);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS payment_txn (
    payment_id      VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    due_date        DATE         NOT NULL,
    amount          BIGINT       NOT NULL CHECK (amount >= 0),
    allocation      JSONB        NOT NULL,                    -- 지연배상금 → 이자 → 원금
    method          VARCHAR(12)  NOT NULL CHECK (method IN ('AUTO_DEBIT','PAYROLL','INSTANT','PREPAY')),
    result          VARCHAR(10)  NOT NULL CHECK (result IN ('DONE','FAILED')),
    account_txn_ref BIGINT,                                   -- @ext 은행(계좌) transactions.id
    paid_at         TIMESTAMPTZ  NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS delinquency (
    delinquency_id  VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    start_date      DATE         NOT NULL,
    days            INTEGER      NOT NULL,
    amount          BIGINT       NOT NULL,
    stage           VARCHAR(12)  NOT NULL,
    notices         JSONB        NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS rate_change (
    rate_change_id  VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    effective_date  DATE         NOT NULL,
    old_rate        NUMERIC(6,4) NOT NULL,
    new_rate        NUMERIC(6,4) NOT NULL,
    reason          VARCHAR(20)  NOT NULL                     -- RATE_RESET, RATE_CUT, PREF_LOST
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS prepay_request (
    prepay_id       VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    principal       BIGINT       NOT NULL CHECK (principal > 0),
    fee             BIGINT       NOT NULL,
    interest        BIGINT       NOT NULL,
    total           BIGINT       NOT NULL,
    idempotency_key VARCHAR(80)  NOT NULL UNIQUE,
    executed_at     TIMESTAMPTZ  NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS rate_cut_request (
    rate_cut_id     VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    reasons         JSONB        NOT NULL,
    result          VARCHAR(10)  NOT NULL CHECK (result IN ('ACCEPTED','REJECTED')),
    new_rate        NUMERIC(6,4),
    requested_at    TIMESTAMPTZ  NOT NULL,
    notified_at     TIMESTAMPTZ  NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS withdrawal_request (
    withdrawal_id   VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    deadline        DATE         NOT NULL,
    refund_total    BIGINT       NOT NULL,
    status          VARCHAR(10)  NOT NULL CHECK (status IN ('ACCEPTED','REFUSED')),
    requested_at    TIMESTAMPTZ  NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS term_change_request (
    term_change_id  VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    items           JSONB        NOT NULL,
    result          VARCHAR(10)  NOT NULL CHECK (result IN ('APPROVED','REJECTED')),
    new_term        INTEGER,
    requested_at    TIMESTAMPTZ  NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS certificate (
    cert_no         VARCHAR(40)  PRIMARY KEY,
    contract_no     VARCHAR(20)  NOT NULL REFERENCES loan_account(contract_no),
    cert_type       VARCHAR(20)  NOT NULL CHECK (cert_type IN ('BALANCE','INTEREST','PAYOFF')),
    doc_hash        VARCHAR(64)  NOT NULL,
    issued_at       TIMESTAMPTZ  NOT NULL
);

-- @domain 대출관리
CREATE TABLE IF NOT EXISTS notification (
    notification_id VARCHAR(40)  PRIMARY KEY,
    user_id         BIGINT,                                   -- @ext 회원·개인정보 (알림 수신자)
    application_id  VARCHAR(40)  REFERENCES loan_application(application_id),
    contract_no     VARCHAR(20)  REFERENCES contract(contract_no),
    event_code      VARCHAR(30)  NOT NULL,
    message         VARCHAR(300) NOT NULL,                    -- 개인정보 없는 문구만
    sent_at         TIMESTAMPTZ  NOT NULL
);

-- =====================================================================
-- @domain 보안·감사 (공통 플랫폼)
-- =====================================================================

-- @domain 보안·감사
CREATE TABLE IF NOT EXISTS llm_call_log (
    call_id         VARCHAR(40)  PRIMARY KEY,
    application_id  VARCHAR(40)  REFERENCES loan_application(application_id),
    use_case_id     VARCHAR(20)  NOT NULL,
    prompt_version  INTEGER      NOT NULL,
    model_tier      VARCHAR(10)  NOT NULL,
    provider        VARCHAR(20)  NOT NULL,
    input_hash      VARCHAR(64)  NOT NULL,                    -- 원문 대신 해시
    output_masked   TEXT,
    validation      JSONB        NOT NULL,
    fallback_used   BOOLEAN      NOT NULL,
    latency_ms      INTEGER      NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 보안·감사
CREATE TABLE IF NOT EXISTS idempotency_key (
    idem_key        VARCHAR(80)  PRIMARY KEY,
    scope           VARCHAR(30)  NOT NULL,
    result_ref      VARCHAR(80)  NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL
);

-- @domain 보안·감사
CREATE TABLE IF NOT EXISTS audit_log (
    audit_seq       INTEGER      PRIMARY KEY AUTOINCREMENT,   -- PostgreSQL: BIGSERIAL
    entity          VARCHAR(30)  NOT NULL,
    entity_id       VARCHAR(40)  NOT NULL,
    action          VARCHAR(40)  NOT NULL,
    actor           VARCHAR(40)  NOT NULL,
    payload_hash    VARCHAR(64)  NOT NULL,                    -- 내용은 해시만(개인정보 미저장)
    prev_hash       VARCHAR(64)  NOT NULL,
    row_hash        VARCHAR(64)  NOT NULL,                    -- 해시 체인(위변조 탐지)
    created_at      TIMESTAMPTZ  NOT NULL
);
-- 감사 로그는 추가만 가능(수정·삭제 금지). PostgreSQL에서는 같은 역할의 트리거 함수 또는 권한(REVOKE UPDATE, DELETE)으로 구현
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;

-- @domain 보안·감사
CREATE TABLE IF NOT EXISTS demo_scenario (                   -- 체험 고객(데모 전용, 회원 DB 통합 시 제거)
    scenario_key    VARCHAR(20)  PRIMARY KEY,
    label           VARCHAR(80)  NOT NULL,
    profile         JSONB        NOT NULL,
    existing_loans  JSONB        NOT NULL,
    defects         JSONB        NOT NULL
);
