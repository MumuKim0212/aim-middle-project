# 카드 백엔드 개발 명세

상태: 제안 (구현 시작 전에 팀이 확정) · 대상: 카드 API 서버

이 문서는 **기획서가 정한 동작을 서버에서 어떻게 구현할지**를 정한다. 기획서와 충돌하면 기획서([docs/card](../../card/README.md))가 우선이고, 이 문서를 고친다.

- 기획서가 정한 것: API 계약, 오류 코드, 상태 전이, 금액 계산 기준 → [00-api-common.md](../../card/00-api-common.md)와 기능별 문서(01~07)
- 이 문서가 정하는 것: DB 설계, 계산 구현 방법, 동시성·멱등성 저장, 서버 간 계약, 요청 처리 세부, 로그·보관, 테스트 지원

## 1. 전제

- 스택은 FastAPI + PostgreSQL이다 ([공통 기획서 1장](../../common/공통.md)). SQL은 PostgreSQL을 기준으로 쓴다 (MySQL에서도 같은 구조로 만들 수 있는 수준으로만 표기한다).
- 카드·계좌·인증은 **한 서버(모놀리스)의 모듈**이다. 파트 사이 호출은 HTTP가 아니라 같은 프로세스의 함수 호출이다 (5절).
- 시간: DB에는 UTC `TIMESTAMPTZ`로 저장하고, 날짜 경계·"오늘" 계산은 `Asia/Seoul`(KST)로 한다. 현재 시각은 `Clock`을 주입받아 쓴다 (테스트에서 바꾸기 위해).

## 2. DB 설계

### 2.1 공통 규칙

| 항목 | 규칙 |
|------|------|
| 금액 | `BIGINT`(원). 소수 없음 |
| 날짜 / 일시 | `DATE` / `TIMESTAMPTZ` |
| ID | 카드 파트 자체 ID는 `VARCHAR(40)`. 접두어 + 정렬 가능한 ID(ULID 등). 예: `card_01J...`. 같은 종류 ID끼리 사전순 = 생성순이어야 커서 정렬이 안정적이다 |
| 사용자·계좌 ID | `BIGINT` (`users.id`, 계좌 `id`). JSON은 숫자 ([공통 기획서 6장](../../common/공통.md)) |
| 문자열 enum | `VARCHAR` + `CHECK`. DB enum 타입은 쓰지 않는다 |
| 공통 컬럼 | `created_at TIMESTAMPTZ NOT NULL`, 수정이 있는 테이블은 `updated_at TIMESTAMPTZ NOT NULL` |
| 외래 키 | 카드 도메인 안에서는 FK를 건다. 사용자·계좌 도메인 참조(`user_id`, `payment_account_id`)는 다른 담당 소유라 **논리 참조**로 둔다 (`BIGINT` 값만 저장하고 FK·`ON DELETE` 규칙은 두지 않는다) |

### 2.2 테이블 한눈에 보기

```
card_products 1 ── * cards 1 ── * card_status_history
                      │
                      └ 1 ── * card_transactions (취소는 original_id로 승인 거래를 가리킴)

card_applications (신청 기록) ── result_card_id → cards
card_issue_quota   (사용자·종류별 락 대상)
idempotency_keys   (카드 신청 멱등성)
```

### 2.3 `card_products` (상품)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `id` | VARCHAR(40) | X | PK. 예: `prod_debit_01`, `prod_credit_01` |
| `type` | VARCHAR(6) | X | `credit` \| `debit` |
| `name` | VARCHAR(50) | X | 상품명 |
| `description` | VARCHAR(200) | X | 한 줄 설명 |
| `active` | BOOLEAN | X | 신청 가능 여부 |

### 2.4 `cards` (카드)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `id` | VARCHAR(40) | X | PK |
| `user_id` | BIGINT | X | 소유 회원 (`users.id`, 논리 참조) |
| `product_id` | VARCHAR(40) | X | FK → `card_products` |
| `name` | VARCHAR(50) | X | 발급 시점의 상품명 (스냅샷) |
| `type` | VARCHAR(6) | X | `credit` \| `debit` |
| `number_last4` | CHAR(4) | X | 카드 번호 끝 4자리 (전체 번호는 저장하지 않는다. 6절) |
| `expiry` | CHAR(5) | X | `MM/YY` |
| `status` | VARCHAR(12) | X | `active` \| `suspended` \| `lost` \| `terminated` |
| `issued_at` | DATE | X | 발급일 (KST) |
| `payment_account_id` | BIGINT | X | 결제 계좌 (계좌 `id`, 논리 참조) |
| `payment_bank_name` | VARCHAR(30) | X | 결제 계좌 은행명 (스냅샷) |
| `payment_account_masked` | VARCHAR(20) | X | 마스킹 계좌 번호 (스냅샷) |
| `payment_day` | SMALLINT | O | 결제일 1~28 (신용만) |
| `credit_limit` | BIGINT | O | 신용 한도 (신용만) |
| `debit_per_tx` | BIGINT | O | 체크 1회 한도 (체크만) |
| `debit_per_day` | BIGINT | O | 체크 1일 한도 (체크만) |
| `suspended_at` | TIMESTAMPTZ | O | 일시정지 일시 (정지 중일 때만) |
| `lost_at` | TIMESTAMPTZ | O | 분실 신고 일시 |
| `lost_reason` | VARCHAR(6) | O | `lost` \| `stolen` |
| `terminated_at` | TIMESTAMPTZ | O | 해지 일시 |
| `terminated_reason` | VARCHAR(20) | O | `unused`, `benefit_complaint`, `other_card`, `lost_cleanup`, `other` (선택 입력이라 비어 있을 수 있음) |
| `created_at` / `updated_at` | TIMESTAMPTZ | X | |

**결제 계좌 스냅샷**: 은행명·마스킹 번호는 발급할 때 `get_account`(5절)로 받아 카드에 함께 저장한다. 카드 목록·상세가 계좌 파트를 매번 부르지 않게 하려는 것이다 (잔액만 03 청구 조회에서 실시간으로 가져온다). 계좌 번호와 은행명은 바뀌지 않는다고 본다. 결제 계좌를 쓰는 해지 안 된 카드가 있으면 그 계좌는 해지할 수 없다 (`count_active_cards`, 5절). 계좌 변경 정책은 이번 범위 밖이다.

**제약 (`CHECK`)**

- 종류별 필수·금지 컬럼
  - `type = 'credit'` 이면 `payment_day`, `credit_limit`은 NOT NULL이고 `debit_per_tx`, `debit_per_day`는 NULL
  - `type = 'debit'` 이면 그 반대
- `payment_day BETWEEN 1 AND 28`, `credit_limit > 0`, `debit_per_tx > 0`, `debit_per_day > 0`
- 상태와 시각이 맞아야 한다
  - `(status = 'suspended') = (suspended_at IS NOT NULL)`
  - `status = 'lost'` 이면 `lost_at` NOT NULL
  - `status = 'terminated'` 이면 `terminated_at` NOT NULL
  - `(lost_at IS NOT NULL) = (lost_reason IS NOT NULL)`
  - `status IN ('active', 'suspended')` 이면 `lost_at`, `terminated_at`이 NULL (분실·해지에서 되돌아올 수 없다)
  - 분실 후 해지한 카드는 `lost_at`, `lost_reason`이 값을 유지한다

**인덱스·유니크**

- `UNIQUE (user_id, number_last4)` — 같은 회원의 모든 카드(해지 포함)에서 끝 4자리가 겹치지 않는다
- `INDEX (user_id, status)` — 목록 조회, 보유 장수 계산
- `INDEX (payment_account_id, status)` — `count_active_cards(account_id)` (5절)

### 2.5 `card_status_history` (상태 이력)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `id` | VARCHAR(40) | X | PK |
| `card_id` | VARCHAR(40) | X | FK → `cards` |
| `user_id` | BIGINT | X | 요청한 회원 (`users.id`, 논리 참조) |
| `action` | VARCHAR(12) | X | `issue` \| `suspend` \| `resume` \| `report_lost` \| `terminate` |
| `from_status` | VARCHAR(12) | O | 이전 상태. `issue`는 NULL |
| `to_status` | VARCHAR(12) | X | 새 상태 |
| `occurred_at` | TIMESTAMPTZ | X | 일시 |
| `request_id` | VARCHAR(40) | O | 요청 ID (7절) |

- 상태 변경과 같은 트랜잭션에서 기록한다. 인덱스 `(card_id, occurred_at)`. 이력 조회 API는 이번 범위에 없다.

### 2.6 `card_transactions` (거래)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `id` | VARCHAR(40) | X | PK |
| `card_id` | VARCHAR(40) | X | FK → `cards` |
| `kind` | VARCHAR(8) | X | `approval` \| `cancel` |
| `occurred_at` | TIMESTAMPTZ | X | 승인·취소 일시 |
| `merchant` | VARCHAR(100) | X | 가맹점명 |
| `amount` | BIGINT | X | 항상 양수 |
| `installment_months` | SMALLINT | X | 0 = 일시불. 기본 0 |
| `original_id` | VARCHAR(40) | O | 취소일 때 원 승인 거래 (FK → 자기 자신) |

**제약**

- `amount > 0`
- `installment_months = 0 OR installment_months BETWEEN 2 AND 12` — 1개월 할부는 일시불과 같으므로 없다. 최대 12개월은 개발 기본값이다 (기획서 확정 사항 아님)
- `kind = 'approval'` 이면 `original_id` NULL
- `kind = 'cancel'` 이면 `original_id` NOT NULL, `installment_months = 0`
- `UNIQUE (original_id)` — 승인 한 건에 취소는 최대 1건 (NULL은 여러 개 허용)
- **행 사이 규칙은 `CHECK`로 못 막으므로 서비스·적재 코드에서 검사한다**: 취소의 `card_id`가 원 승인과 같고, `amount`가 원 승인과 같고, `occurred_at`이 원 승인보다 뒤이며, 원 승인이 일시불이다. 체크카드 거래는 `installment_months = 0`이다.
- 인덱스 `(card_id, occurred_at DESC, id DESC)`

**거래가 들어오는 길**: 결제 승인 처리는 범위 밖이므로, 거래는 시드 스크립트·임포트로만 들어온다 (10절). 거래를 만드는 API는 없다.

### 2.7 `card_applications` (신청 기록)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `id` | VARCHAR(40) | X | PK |
| `user_id` | BIGINT | X | `users.id` (논리 참조) |
| `type` | VARCHAR(6) | X | `credit` \| `debit` |
| `product_id` | VARCHAR(40) | X | FK → `card_products` |
| `payment_account_id` | BIGINT | X | 계좌 `id` (논리 참조) |
| `payment_day` | SMALLINT | O | 신용만 |
| `income_range` | VARCHAR(10) | O | 신용만. `none`, `lt_10m`, `10m_20m`, `20m_40m`, `40m_70m`, `gte_70m` |
| `recipient` | VARCHAR(20) | X | |
| `phone` | VARCHAR(13) | X | `010-0000-0000` |
| `address_line1` | VARCHAR(100) | X | |
| `address_line2` | VARCHAR(100) | O | |
| `agree_card_terms` | BOOLEAN | X | 항상 true |
| `agree_privacy` | BOOLEAN | X | 항상 true |
| `agree_credit_inquiry` | BOOLEAN | O | 신용만 |
| `status` | VARCHAR(8) | X | `approved` \| `rejected` |
| `reject_reason` | VARCHAR(30) | O | `INCOME_INSUFFICIENT` (거절일 때만) |
| `granted_limit` | BIGINT | O | 신용 승인일 때만 |
| `result_card_id` | VARCHAR(40) | O | 승인일 때 FK → `cards` |
| `requested_at` | TIMESTAMPTZ | X | |

- 카드 비밀번호(`cardPin`)는 **저장하지 않는다**. 카드 신청 요청에는 간편비밀번호가 없다 (본인 재확인은 세션, 4절).
- 인덱스 `(user_id, requested_at)`.
- 개인정보(수령인·연락처·주소) 보관 기간은 팀이 정한다. 제안: **거절된 신청은 90일 뒤 개인정보 컬럼을 비운다**(삭제 배치). 승인된 신청은 카드가 있는 동안 보관한다. 해지 후 보관 기간은 팀 합의가 필요하다.

### 2.8 `card_issue_quota` (신청 직렬화용 락 대상)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `user_id` | BIGINT | X | PK의 일부 |
| `type` | VARCHAR(6) | X | PK의 일부 |

- 회원·종류별로 한 행 (`PRIMARY KEY (user_id, type)`). 값은 없고 **행 락만 건다**. 처음 신청할 때 만든다 (`INSERT ... ON CONFLICT DO NOTHING`).
- 카드가 아직 없는 회원에게도 락을 걸 수 있게 하려고 카드 테이블이 아니라 별도 테이블을 쓴다. `users` 테이블은 인증 담당 소유라 거기에 락을 걸 수 없다.

### 2.9 `idempotency_keys` (카드 신청 멱등성)

| 컬럼 | 타입 | NULL | 설명 |
|------|------|:----:|------|
| `user_id` | BIGINT | X | PK의 일부 |
| `idem_key` | VARCHAR(36) | X | PK의 일부 (UUID 문자열) |
| `fingerprint` | CHAR(64) | X | 요청 본문 지문 (4.3) |
| `response_status` | SMALLINT | O | 항상 201. 처리 중에는 NULL |
| `response_body` | TEXT | O | 저장한 응답 JSON |
| `created_at` | TIMESTAMPTZ | X | |
| `expires_at` | TIMESTAMPTZ | X | 생성 + 24시간 |

- 인덱스 `(expires_at)`. 만료 행은 매시간 삭제한다. 조회할 때 만료된 키는 없는 것으로 본다.

## 3. 금액 계산 구현

기획서의 [공통 계산 기준 6절](../../card/00-api-common.md#6-금액-계산-기준-공통)이 정본이다. 여기서는 구현 방법만 적는다. 상세·한도 조회·청구·해지 판정이 **같은 함수 하나**를 쓴다 (`computeCycles`).

### 3.1 입력과 날짜 규칙

- 입력: 신용카드 한 장(`payment_day = D`), 그 카드의 거래, 오늘 `T`(KST 날짜)
- 거래의 날짜 = `occurred_at`을 KST로 바꾼 날짜
- `P(날짜)` = 그 날짜가 속한 달의 **다음 달 `D`일**
- `due(m, i)` = `m`월에서 `i`개월 뒤의 `D`일 (`m + i`월 `D`일)

### 3.2 계산 (의사코드)

```
cycles = {}                                  // 결제일 P → 합계(원)

for tx in 승인 거래:
    if tx.installment_months == 0:
        cycles[P(날짜(tx))] += tx.amount
    else:
        n = tx.installment_months
        for i in 1..n:
            cycles[due(월(tx), i)] += piece(tx.amount, n, i)

for tx in 취소 거래:
    a  = 원 승인 거래
    Pa = P(날짜(a))
    P  = (날짜(tx) <= Pa) ? Pa : P(날짜(tx))     // 결제일 당일 포함
    cycles[P] -= tx.amount

B(P) = max(0, cycles[P])                      // 음수는 0, 이월 없음
used = Σ B(P)   (P >= T 인 것만)

piece(A, n, i) = (i < n) ? floor(A / n) : A - floor(A / n) * (n - 1)
```

### 3.3 읽을 거래 범위 (성능)

- 이용 금액에 영향을 주는 거래는 모두 `occurred_at ≥ (T가 속한 달 − 13개월)의 1일 00:00 KST` 안에 있다 (할부 최대 12개월). **단순한 구현은 카드의 거래를 이 범위로 전부 읽어 메모리에서 계산한다.** 카드는 회원당 최대 3장(신용)이고 거래 수도 작아 이 방식으로 충분하다.
- 더 줄이려면: 일시불·취소는 `M0` 월 1일부터만 읽어도 된다. `M0 = (D ≥ day(T)) ? month(T) − 1 : month(T)`.
- 취소를 계산할 때는 원 승인 거래를 함께 읽는다 (조인).
- 계산 결과는 캐시하지 않는다. 쓰기(상태 변경)가 계산 결과에 영향을 주지 않으므로 캐시가 필요해지면 그때 `(card_id, T)` 단위로 짧게 둔다.

### 3.4 이용 비율 (정수 연산)

```
rate10     = (used * 1000 + total / 2) / total      // 정수 나눗셈, 반올림(half up)
usageRate  = min(1000, rate10) / 10.0               // 소수 첫째 자리
```

- 확인: 1,208,000 / 3,000,000 → `(1,208,000,000 + 1,500,000) / 3,000,000 = 403` → `40.3`. 45,000 / 500,000 → `90` → `9.0`. 308,000 / 3,000,000 → `103` → `10.3`.
- JSON 값은 숫자(`40.3`, `9.0`)로 내려준다. 화면이 소수 첫째 자리까지 표시한다.

### 3.5 청구 화면용 묶음 (03)

1. 해지되지 않은 신용카드마다 다음 결제일을 구한다 (`T` 이후 당일 포함 가장 가까운 `D`일).
2. 그 주기의 `B(P)`와 내역(`items`)을 만든다. `B(P) = 0`인 카드는 뺀다.
3. `(결제일, 결제 계좌)`로 묶고 묶음 합계를 구한다. 정렬은 결제일 → `accountId`.
4. 묶음마다 `get_account`(5절)로 잔액을 가져온다 (계좌당 한 번). 실패하면 그 묶음만 `balanceStatus: "unavailable"`.
5. `thisMonthTotal` = `isCurrentMonth`인 묶음 합계. `nextPaymentDate` = 묶음 중 가장 빠른 결제일.
- `items`의 `installment` 내역: 그 주기에 해당하는 회차만 넣고, 금액은 `piece(...)`다. 할부의 `occurredAt`은 원 승인 일시다.

### 3.6 해지 판정 (07)

- `used == 0` 이면 해지 가능. 아니면 `unpaidAmount = used`, `firstDueDate = min{ P : P ≥ T, B(P) > 0 }`.

### 3.7 검증용 값

기획서 [00 10.5](../../card/00-api-common.md#105-기준-데이터에서-나오는-값-오늘--2026-11-04)의 값(420,000 / 900,000 / 308,000, `used` 1,208,000 등)과 03·05의 계산 단위 테스트(T16~T19, T25~T27 / T11~T12)를 그대로 단위 테스트로 만든다.

## 4. 동시성·트랜잭션

DB는 `READ COMMITTED`를 가정한다. 본인 재확인은 세션 값을 읽는 `pin_verified(request)` 확인(비용이 작고 DB 락과 무관)뿐이므로, **트랜잭션 밖에서** 먼저 확인하고 그 뒤 짧은 트랜잭션에서 조건부로 갱신한다.

### 4.1 상태 변경 (정지·해제·분실·해지)

1. 입력 검증 → 카드 조회(소유권 → `404`) → 상태 확인(`409`) → (해지만) 미결제 확인(`409`) — 모두 락 없이 읽기
2. 본인 재확인 여부 확인: `pin_verified(request)` (세션 확인, 트랜잭션 밖). 거짓이면 `PinVerificationRequired` → `403 PIN_VERIFICATION_REQUIRED`, 카드는 바뀌지 않는다
3. 트랜잭션 시작
   - 정지·해제·분실:

     ```sql
     UPDATE cards
        SET status = :to, suspended_at = :suspendedAt, lost_at = :lostAt, lost_reason = :lostReason, updated_at = :now
      WHERE id = :id AND user_id = :user AND status IN (:allowed)
     ```

     갱신된 행이 0이면 카드를 다시 읽어 없으면 `404`, 있으면 `409 CARD_STATE_INVALID`(`currentStatus`, `allowedStatuses`)를 돌려준다.
   - 해지: `SELECT ... FOR UPDATE`로 카드 행을 잠그고, `used`를 **다시 계산**해서 0이 아니면 `409 CARD_TERMINATE_BLOCKED_UNPAID`. 0이면 `status = 'terminated'`로 갱신한다 (조건: 현재 상태가 `terminated`가 아닐 때).
   - `card_status_history` 한 줄 추가
4. 커밋

1단계 뒤 3단계 사이에 상태가 바뀌면 조건부 갱신이 0행이 되어 `409`가 된다.

### 4.2 카드 신청 (3장 제한 + 멱등성)

1. 락 없는 사전 검사: 입력 검증 → 멱등성 조회(저장된 응답이 있으면 재생, 본문이 다르면 `422`) → 결제 계좌 확인(`get_account(user, paymentAccountId)`, 없음·타인·저축예금 아님·해지는 `404 ACCOUNT_NOT_FOUND`) → 신청 자격(`get_age(user) >= 19`) → 보유 장수(빠른 거절)
2. 본인 재확인 여부 확인: `pin_verified(request)` (세션 확인, 트랜잭션 밖). 거짓이면 `PinVerificationRequired` → `403 PIN_VERIFICATION_REQUIRED`, 신청 기록·멱등성 행은 만들지 않는다
3. 트랜잭션 시작
   1. `INSERT INTO idempotency_keys (...)` (응답 컬럼은 NULL). 같은 `(user_id, idem_key)`가 이미 있으면 DB가 그 트랜잭션이 끝날 때까지 기다리게 하고, 끝난 뒤 저장된 응답을 읽어 그대로 돌려준다 (동시에 같은 키가 온 경우)
   2. `card_issue_quota (user_id, type)` 행을 `INSERT ... ON CONFLICT DO NOTHING` 한 뒤 `SELECT ... FOR UPDATE`로 잠근다
   3. 보유 장수를 다시 센다 (해지·분실 제외). 한도(3장)에 이미 도달했으면 롤백하고 `409 CARD_COUNT_LIMIT_EXCEEDED`
   4. 심사: 신용이면 소득 구간표로 승인·거절 결정
   5. `card_applications` 저장. 승인이면 `cards` 저장(번호 끝 4자리 생성, 6절), `card_status_history`(`issue`) 저장
   6. 멱등성 행의 `response_status`(201), `response_body`를 채운다
4. 커밋

- 오류 응답과 `5xx`는 트랜잭션이 롤백되므로 멱등성 행도 함께 사라진다. 그래서 오류는 저장되지 않고, 같은 키로 다시 시도하면 새로 처리된다 (기획서 규칙과 같다).
- 락 순서는 항상 `멱등성 행 → quota 행`이다. 데드락을 막는다.
- 거절 응답(`201`, `status: "rejected"`)은 정상 처리이므로 커밋하고 저장한다.

### 4.3 멱등성 지문 (fingerprint)

- 요청 본문을 다음과 같이 정규화한 뒤 SHA-256(소문자 16진수)으로 만든다.
  1. 서버 기본값을 적용한다 (신용인데 `paymentDay`가 없으면 25) — 생략한 요청과 25로 보낸 요청은 같은 본문이다
  2. 문자열은 앞뒤 공백 제거 후 NFC 정규화
  3. **`cardPin`은 지문에서 뺀다** (지문에서 비밀번호가 역산되지 않게 하고, 비밀번호만 고친 재시도를 같은 요청으로 본다)
  4. 키 이름을 사전순으로 정렬한 JSON으로 직렬화
- 만료: 24시간. 만료된 키는 새 요청으로 처리한다.

## 5. 서버 간 계약 (계좌·인증)

기획서 [00 7절](../../card/00-api-common.md#7-다른-담당에-요구하는-인터페이스)의 계약을 서버 코드 관점에서 정한다. 담당자와 합의해서 확정한다.

### 5.1 인터페이스

| 호출 | 입력 | 결과 | 카드 서버의 처리 |
|------|------|------|------------------|
| `get_account(user, account_id)` (계좌 제공) | 세션 `user`, 계좌 ID(숫자) | `{ accountId, bankName, accountMasked, balance, productType, status }`. 내 계좌가 아니거나 없으면 `NOT_FOUND` | 06: `404 ACCOUNT_NOT_FOUND` (결제 계좌 후보가 아닌 내 계좌, 즉 저축예금이 아니거나 해지된 계좌도 같은 `404`. 아래 참고). 03: 잔액 조회 실패는 `balanceStatus: "unavailable"`로 내려주고 오류로 만들지 않는다 |
| `GET /api/accounts?purpose=card_payment` (계좌 제공) | - | `{ items: [{ accountId, bankName, accountMasked }] }`. 본인의 active 저축예금만 | 프론트가 REST로 직접 호출한다. 카드 서버는 호출하지 않는다 |
| `pin_verified(request)` (인증 제공) | 세션 `user` | `bool`. 5분 안에 `POST /api/auth/pin/verify`를 통과했으면 참 (세션 `pin_verified_at`) | 거짓이면 쓰기 함수가 `PinVerificationRequired`를 던진다 → `403 PIN_VERIFICATION_REQUIRED`. 4절 |
| `get_age(user)` (인증 제공) | 세션 `user` | 만 나이(정수). `birthDate`는 NOT NULL이다 | 만 19세 확인: `get_age(user) >= 19` |
| `count_active_cards(account_id)` (**카드 제공**) | 계좌 ID | 그 계좌를 결제 계좌로 쓰는 `terminated`가 아닌 카드 수 | 계좌 파트가 저축예금 해지(ACC-15) 때 0이 아니면 거부한다. 카드 서버는 호출하지 않는다 |

- `user`는 **세션에서 `current_user`가 준 값**만 쓰고 요청 본문의 값은 받지 않는다.
- 결제 계좌 후보 판정(저축예금이고 active)은 `get_account` 응답의 `productType`·`status`로 한다. 이 두 필드는 계좌.md에 아직 없어 계좌 담당이 추가해야 한다 (공통 기획서 8장, 11절).
- `count_active_cards`는 `SELECT count(*) FROM cards WHERE payment_account_id = :id AND status <> 'terminated'`다. 일시정지·분실 카드도 센다 (해지되지 않았기 때문).

### 5.2 호출 방식과 장애 처리

- 호출: 같은 프로세스의 함수 호출이다. HTTP·서비스 간 토큰은 쓰지 않는다 (공통.md 1장).
- 재시도: 조회(`get_account`, `get_age`)는 1회까지 재시도한다.
- 장애 시: `get_account`(06) 호출이 실패하면 `503 ACCOUNT_SERVICE_UNAVAILABLE`, `get_age` 호출이 실패하면 `503 MEMBER_SERVICE_UNAVAILABLE`. 같은 프로세스의 모듈 호출이 예외를 던졌다는 뜻이다. 둘 다 카드 상태를 바꾸지 않는다.

### 5.3 서비스 함수 계층

REST 라우터와 자연어 에이전트의 도구([08-natural-language.md](../../card/08-natural-language.md))는 **같은 서비스 함수**를 부른다. 라우터는 `Depends(current_user)`로 받은 `user`를 넘기고, 자연어 도구는 서버가 세션에서 넣은 `user`를 넘긴다. 두 경로가 다른 규칙을 갖지 않는다. (표의 경로는 모두 `/api` 아래다.)

| 함수 | 종류 | 대응 API |
|------|------|----------|
| `list_cards(user, ...)` | 조회 | `GET /cards` |
| `get_card(user, card_id)` | 조회 | `GET /cards/{cardId}` |
| `list_transactions(user, ...)` | 조회 | `GET /card-transactions` |
| `get_transaction(user, transaction_id)` | 조회 | `GET /card-transactions/{id}` |
| `get_billing_upcoming(user)` | 조회 | `GET /card-billing/upcoming` |
| `get_limit(user, card_id)` | 조회 | `GET /cards/{cardId}/limit` |
| `suspend_card(user, card_id)` | 쓰기 | `POST /cards/{cardId}/suspend` |
| `resume_card(user, card_id)` | 쓰기 | `POST /cards/{cardId}/resume` |
| `report_lost(user, card_id, reason)` | 쓰기 | `POST /cards/{cardId}/report-lost` |
| `check_terminate(user, card_id)` | 조회 | `GET /cards/{cardId}/termination-check` |
| `terminate_card(user, card_id, reason)` | 쓰기 | `POST /cards/{cardId}/terminate` |
| `get_apply_eligibility(user, ...)` | 조회 | `GET /card-applications/eligibility` |
| `apply_card(user, request, idempotency_key)` | 쓰기 | `POST /card-applications` |
| `count_active_cards(account_id)` | 조회 | 계좌 파트가 호출 (REST 없음) |

- 쓰기 함수(정지·해제·분실·해지·신청)는 스스로 `pin_verified(request)`를 부른다 (4절). 거짓이면 `PinVerificationRequired`를 던지고, 라우터가 `403 PIN_VERIFICATION_REQUIRED`(details 없음)로 바꾼다. 자연어 도구는 같은 예외를 `{ status: "pin_verification_required" }`로 바꾼다 (공통.md 9.2).
- 함수는 소유권·상태·업무 검사를 하고 도메인 오류(`CARD_NOT_FOUND`, `CARD_STATE_INVALID` 등)를 던진다. HTTP 상태로 바꾸는 일은 라우터가, 자연어 응답으로 바꾸는 일은 도구가 맡는다.
- `user`가 아닌 사용자 ID를 받는 함수는 만들지 않는다 (`count_active_cards`만 계좌 ID를 받는 예외).

## 6. 카드 번호·CVC·카드 비밀번호

- **카드 전체 번호와 CVC는 만들지도 저장하지도 않는다.** 이번 범위에서 전체 번호가 필요한 기능이 없다 (화면은 끝 4자리만 쓴다). 서버는 끝 4자리(`number_last4`)만 생성한다.
  - `shortcut: 전체 번호·CVC 없음, 실물 카드 발급이나 결제 승인 연동이 생기면 전체 번호는 암호화 컬럼(KMS 키)으로 추가하고 CVC는 발급 응답에서 한 번만 쓰고 저장하지 않는다`
- 끝 4자리 생성: 트랜잭션 안에서 4자리 난수를 만들고 `UNIQUE (user_id, number_last4)` 충돌이 나면 새 값으로 최대 10번 다시 만든다 (세이브포인트 사용). 모두 실패하면 `500`이다 (회원당 카드 이력이 1만 건에 가까워야 발생하므로 현실적으로 일어나지 않는다).
- 유효기간: 발급일(KST)에서 5년 뒤의 `MM/YY`.
- **`cardPin`은 저장하지 않는다.** 검증 후 버린다. `PIN_TOO_SIMPLE` 판정: 네 자리를 `d0 d1 d2 d3`라 할 때, 모두 같거나(`d0=d1=d2=d3`), 인접 자리 차이가 모두 `+1`이거나(`0123`, `1234`, `6789`), 모두 `-1`이다(`3210`, `4321`, `9876`). `7890`은 9→0이 차이 `-9`라서 단순하지 않다.
- 카드 API는 **간편비밀번호를 받지 않는다.** 본인 재확인은 세션의 `pin_verified_at`을 `pin_verified(request)`로 확인하는 것뿐이다 (4절).

## 7. 요청 처리 세부 (형식 오류·검증·로그)

### 7.1 요청 형식 오류

| 상황 | 응답 |
|------|------|
| 깨진 JSON, 본문 최상위가 객체가 아님 | `400 VALIDATION_FAILED`, `fields: [{ "field": "$", "reason": "INVALID_FORMAT" }]` |
| 필드 타입이 틀림 (예: `cardPin`이 숫자 `1234`) | `400 VALIDATION_FAILED`, 해당 필드 `INVALID_FORMAT` |
| 알 수 없는 필드 | **무시한다** (오류로 만들지 않는다) |
| `Content-Type`이 JSON이 아님 | `415`, `code: "UNSUPPORTED_MEDIA_TYPE"` |
| 없는 경로 | `404`, `code: "NOT_FOUND"` |
| 허용되지 않는 메서드 | `405`, `code: "METHOD_NOT_ALLOWED"` |

`415`, `404 NOT_FOUND`, `405`는 프레임워크 수준 오류라 [오류 코드 표](../../card/00-api-common.md#3-오류-코드-표)에는 넣지 않았다. 응답 모양은 같다 (`code`, `message`).

### 7.2 필드 표기·문자열 처리

- `details.fields[].field`: 중첩 필드는 점 표기(`address.line1`, `agreements.privacy`), 헤더는 헤더 이름(`Idempotency-Key`), 쿼리는 이름(`from`).
- 문자열 길이는 **NFC 정규화 후 유니코드 코드포인트 수**로 센다. 이름·주소·검색어는 앞뒤 공백을 제거한 뒤 검사한다.
- 가맹점 검색: 소문자로 바꾼 값으로 부분 일치(`LIKE`)를 하되 `%`, `_`, `\`는 이스케이프해 글자 그대로 찾는다.

### 7.3 로그와 개인정보

- **본문을 로그에 남기지 않는 값**: `cardPin`, 세션 쿠키(`Cookie`, `Set-Cookie`), 이름, 전화번호, 주소, 생년월일. 간편비밀번호는 어떤 로그에도 남기지 않는다 (공통.md 4장).
- `Idempotency-Key`는 앞 8자만 로그에 남긴다. 잔액은 로그에 남기지 않는다.
- 카드·신청 테이블의 SQL 바인드 파라미터 로그는 끈다.
- 모든 요청에 `request_id`를 만들어(`X-Request-Id`) 오류 로그와 `card_status_history`에 남긴다.

## 8. 커서·정렬·페이지

- **커서**: `{ t: occurred_at(epoch ms), id, f: 필터 지문, u: userId, e: 만료(epoch ms) }`를 JSON → base64url로 만들고 서버 비밀키로 HMAC-SHA256 서명을 붙인다. 서명 불일치, 회원 불일치, 만료(24시간), 필터 지문 불일치는 모두 `400 INVALID_CURSOR`.
- **필터 지문**: `SHA-256( {cardId, from, to, kind, merchant(소문자·trim 적용)} 를 키 순서대로 직렬화 )`.
- **쿼리**: `WHERE (occurred_at, id) < (:t, :id) ... ORDER BY occurred_at DESC, id DESC LIMIT :limit + 1`. 한 건 더 읽어 다음 페이지가 있는지 판단한다.
- **요약(`summary`)**: 같은 필터로 승인 합계·취소 합계·건수를 매 요청 집계한다 (기간 12개월 이내라 충분하다).
- **날짜 경계**: `from` = 그날 00:00 KST 이상, `to` = 그다음 날 00:00 KST 미만.
- **12개월 규칙**: `from ≥ to`의 12개월 전 같은 일자. 그 일자가 없으면(예: `to=2028-02-29`) 그 달의 마지막 날로 맞춘다 (`2027-02-28`).
- `GET /cards`는 페이지를 나누지 않는다. 해지된 카드가 많아지면 `includeTerminated`에 `limit`을 추가한다 (`shortcut: 카드 수가 작다고 가정`).

## 9. 감사·보관

- 상태 이력: 2.5절. 모든 상태 변경과 발급에 남긴다.
- 간편비밀번호 확인 실패(오답 횟수·잠금)는 인증 파트가 `users.pin_failed_count`, `users.PIN_LOCKED_until`로 소유한다. 카드 서버는 기록하지 않는다.
- 신청 개인정보 보관: 2.7절의 제안(거절 건 90일 뒤 비움)을 팀이 확정한다.
- 멱등성 행 정리: 매시간 `expires_at < now` 삭제.

## 10. 데이터 적재·테스트 지원

- **시드**: 기획서 [00 10절 기준 데이터](../../card/00-api-common.md#10-목업-데이터-기준표)(카드, 거래)를 그대로 시드 코드·SQL로 옮긴다. 카드·거래 ID는 `card_001`처럼 사람이 읽는 문자열이어도 되며(`VARCHAR(40)`), 사전순 정렬만 위 8절 요구를 만족하면 된다. 사용자·계좌는 [공통 기획서 7장](../../common/공통.md)의 공통 시드(id 고정)를 쓴다. 카드 시드는 그 id를 `user_id`, `payment_account_id`에 숫자로 넣는다.

  | 기준 데이터 | 시드 |
  |-------------|------|
  | `member_001` ~ `member_004` | `users.id` 1 (user1 김하나) ~ 4 (user4 최아란, 만 19세 미만). user3은 간편비밀번호 미설정이라 먼저 S-07을 끝낸다 |
  | `acc_001`, `acc_002` | 계좌 1 (저축예금, 잔액 1,500,000, `****1234`), 계좌 2 (저축예금, 500,000, `****5678`). 둘 다 user1 |
  | (신규) | 계좌 3 (정기예금 3,000,000), 계좌 4 (정기적금 600,000). user1, 카드 결제 계좌가 될 수 없다 |
  | `acc_900` | 계좌 5 (user2, 300,000, `****9000`) |
  | `acc_401` | 계좌 6 (user4, 100,000, `****4010`) |

  카드 소유: `card_001` ~ `card_005`는 `user_id = 1`, `card_900`은 `user_id = 2`. `payment_account_id`: `card_001`, `card_003`~`card_005` = 1, `card_002` = 2, `card_900` = 5. 결제 계좌 스냅샷의 은행명은 `AIM Bank`다. 이 값에서 `card_002`의 2026-11-25 청구액 900,000원은 계좌 2 잔액 500,000원보다 400,000원 많다 (03의 부족 금액).
- **시계**: `Clock`을 주입한다. 테스트가 "오늘"을 `2026-11-04`로 두고, 03·05·07의 시나리오처럼 `2026-11-26`, `2027-02-01` 등으로 옮길 수 있어야 한다.
- **계좌·인증 함수 대역(fake)**: 잔액 설정, `pin_verified(request)` 결과 정하기(통과 / 확인 이력 없음 / 5분 경과), 장애 흉내(`503`)를 할 수 있게 만든다.
- **초기화**: 각 테스트는 기준 데이터에서 시작한다 (트랜잭션 롤백 또는 비우고 다시 적재).
- **동시성 테스트**: 같은 카드에 정지 2건 동시(04 T22), 신용 신청 2건 동시(06 T40), 같은 `Idempotency-Key` 동시 2건.
- 기획서의 테스트 시나리오(T-번호)를 통합 테스트로 옮기고, 계산 단위 테스트(03 T16~T19·T25~T27, 05 T11~T12)는 `computeCycles`의 단위 테스트로 만든다.

## 11. 합의가 필요한 항목

| 항목 | 상대 | 내용 |
|------|------|------|
| 5.1 서버 간 계약 | 김연준(계좌), 인증 담당 | `get_account`, `pin_verified`, `get_age`의 시그니처, 오류 매핑, 장애 시 동작 |
| 5.1 `count_active_cards` | 김연준(계좌) | 저축예금 해지(ACC-15)에서 호출해 0이 아니면 거부 (공통.md 8장, 계좌.md에 아직 없음) |
| 5.1 결제 계좌 후보 판정 | 김연준(계좌) | 저축예금이 아니거나 해지된 계좌를 카드 서버가 가려내는 방법. 제안: `get_account` 응답에 `productType`·`status`를 추가한다 (공통 기획서 8장) |
| 2.6 할부 허용값 | 팀 | 0 또는 2~12개월 (개발 기본값) |
| 2.7 개인정보 보관 | 팀 | 거절 신청 90일 뒤 비움 (제안), 해지 후 보관 기간 |