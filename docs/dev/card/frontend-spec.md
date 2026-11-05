# 카드 프론트 개발 명세

상태: 제안 (구현 시작 전에 팀이 확정) · 대상: `frontend/` (React 19 + Vite + TypeScript + Tailwind 4 + React Router)

이 문서는 **기획서가 정한 화면·API를 프론트에서 어떻게 구현할지**를 정한다. 기획서([docs/card](../../card/README.md))와 충돌하면 기획서가 우선이고, 이 문서를 고친다.

- 기획서가 정한 것: 화면 구성, 문구, 상태별 화면, API 계약, 오류 처리 → [00-api-common.md](../../card/00-api-common.md)와 기능별 문서(01~07)
- 이 문서가 정하는 것: 라우트·메뉴 연결, 인증 틀, API 클라이언트 함수·타입, 캐시, 목업 서버 제어, 암호 팝업 컴포넌트 계약, 폼 컨트롤·검증 문구, 디자인 토큰, 테스트 도구

## 1. 폴더 구조

```
frontend/src/features/card/
  api/         cardApi.ts (3절의 함수), types.ts (3.4절의 타입), http.ts, errors.ts
  lib/         cycles.ts (청구 주기 계산 순수 함수), format.ts (formatWon, formatDate, formatDateTime)
  mock/        fixtures.ts (00 10절 기준 데이터), mockServer.ts, control.ts, clock.ts
  components/  AccountPinDialog, StatusBadge, PageHeader, EmptyState, ErrorState, Loading ...
  pages/       CardListPage, CardDetailPage, CardPickerPage, TransactionsPage, BillingPage,
               SecurityPage, LimitPage, ApplyPage, ApplyResultPage, TerminatePage
```

- 지금 있는 `features/card/CardPage.tsx`(빈 자리표시 화면)는 `pages/CardListPage.tsx`로 대체하고 지운다.
- 청구 주기 계산(`lib/cycles.ts`)은 [백엔드 명세 3절](backend-spec.md#3-금액-계산-구현)과 같은 알고리즘을 순수 함수로 구현해 **목업 서버와 단위 테스트가 함께** 쓴다.
- API 호출은 `api/` 한 곳에서만 한다. 화면은 `cardApi`의 함수만 부른다.

## 2. 라우트와 메뉴

### 2.1 라우트 표

| 경로 | 화면 | 기획서 |
|------|------|--------|
| `/card` | `CardListPage` | 01 |
| `/card/:cardId` | `CardDetailPage` | 01 |
| `/card/transactions` | `TransactionsPage` | 02 |
| `/card/billing` | `BillingPage` | 03 |
| `/card/security` | `CardPickerPage` (`purpose="security"`) | 04 |
| `/card/:cardId/security` | `SecurityPage` | 04 |
| `/card/limit` | `CardPickerPage` (`purpose="limit"`) | 05 |
| `/card/:cardId/limit` | `LimitPage` | 05 |
| `/card/apply` | `ApplyPage` | 06 |
| `/card/apply/result` | `ApplyResultPage` | 06 |
| `/card/:cardId/terminate` | `TerminatePage` | 07 |

`/card/:cardId`와 `/card/transactions` 같은 고정 경로가 겹쳐 보이지만, React Router는 **고정 세그먼트를 동적 세그먼트보다 먼저** 맞춘다. 카드 ID는 `card_...` 모양이라 이 단어들과 같을 수 없다.

### 2.2 `App.tsx` 구조

```tsx
<Routes>
  <Route element={<Layout />}>
    <Route index element={<HomePage />} />
    <Route path="card" element={<RequireAuth />}>
      <Route index element={<CardListPage />} />
      <Route path="transactions" element={<TransactionsPage />} />
      <Route path="billing" element={<BillingPage />} />
      <Route path="security" element={<CardPickerPage purpose="security" />} />
      <Route path="limit" element={<CardPickerPage purpose="limit" />} />
      <Route path="apply" element={<ApplyPage />} />
      <Route path="apply/result" element={<ApplyResultPage />} />
      <Route path=":cardId" element={<CardDetailPage />} />
      <Route path=":cardId/security" element={<SecurityPage />} />
      <Route path=":cardId/limit" element={<LimitPage />} />
      <Route path=":cardId/terminate" element={<TerminatePage />} />
    </Route>
    <Route path="login" element={<LoginPage />} />  {/* 담당 미정, 4절 참고 */}
  </Route>
</Routes>
```

현재 `App.tsx`에는 `card`, `account`, `ledger`, `loan` 단일 경로만 있다. `card`만 위 중첩 구조로 바꾸고 나머지는 건드리지 않는다.

### 2.3 햄버거 메뉴 연결

지금 `components/MenuPanel.tsx`는 항목이 문자열 배열이고 모두 대분류의 `to`(`/card`)로 이동한다. 아래처럼 항목마다 경로를 갖도록 바꾼다.

| 대분류 | 메뉴 항목 | 경로 |
|--------|-----------|------|
| 계좌 | (비워 둠) | - |
| 카드 | 내 카드 목록·상세 | `/card` |
| 카드 | 이용내역 조회 | `/card/transactions` |
| 카드 | 청구·결제 예정 금액 | `/card/billing` |
| 카드 | 카드 분실·정지·재개 | `/card/security` |
| 카드 | 한도 조회 | `/card/limit` |

- 항목 자료형: `{ label: string; to: string }[]`
- "한도 조회·변경"은 한도 변경 기능이 없으므로 **"한도 조회"로 바꾼다.**

## 3. API 클라이언트

### 3.1 `http.ts` 규칙

- 기본 주소 `/api/v1`, JSON, `Authorization: Bearer <token>` (토큰은 `getAccessToken()` 한 함수에서만 가져온다)
- 요청 시간 제한 10초 (`AbortController`)
- 성공: 본문을 그대로 반환. 오류: [오류 응답](../../card/00-api-common.md#14-오류-응답)을 읽어 `ApiError`로 던진다.
- 응답이 없는 경우: 네트워크 오류는 `ApiError(status 0, code "NETWORK_ERROR")`, 10초 초과는 `ApiError(status 0, code "TIMEOUT")`. 이 두 코드는 **프론트 전용**이다 (서버 오류 코드 표에 없음).
- `Idempotency-Key`가 필요한 요청은 함수 인자로 받아 헤더에 넣는다.

### 3.2 `ApiError`

```ts
export class ApiError extends Error {
  constructor(
    public status: number,            // 0 = 응답 없음
    public code: ApiErrorCode,
    message: string,
    public details?: Record<string, unknown>,
  ) { super(message) }
}

export type ApiErrorCode =
  | 'VALIDATION_FAILED' | 'INVALID_CURSOR' | 'IDEMPOTENCY_KEY_REQUIRED'
  | 'AUTH_REQUIRED'
  | 'ACCOUNT_PIN_MISMATCH' | 'ACCOUNT_PIN_LOCKED'
  | 'CARD_NOT_FOUND' | 'ACCOUNT_NOT_FOUND' | 'TRANSACTION_NOT_FOUND'
  | 'CARD_STATE_INVALID' | 'CARD_COUNT_LIMIT_EXCEEDED' | 'CARD_TERMINATE_BLOCKED_UNPAID'
  | 'APPLICANT_NOT_ELIGIBLE' | 'IDEMPOTENCY_KEY_REUSED'
  | 'INTERNAL_ERROR' | 'ACCOUNT_SERVICE_UNAVAILABLE' | 'MEMBER_SERVICE_UNAVAILABLE'
  | 'NETWORK_ERROR' | 'TIMEOUT'
```

### 3.3 함수 표

| 함수 | 요청 | 반환 | 주로 던지는 `code` |
|------|------|------|--------------------|
| `listCards({ includeTerminated? })` | `GET /cards` | `CardListResponse` | `VALIDATION_FAILED` |
| `getCard(cardId)` | `GET /cards/{id}` | `CardDetail` | `CARD_NOT_FOUND` |
| `listTransactions(params)` | `GET /card-transactions` | `TransactionListResponse` | `VALIDATION_FAILED`, `INVALID_CURSOR`, `CARD_NOT_FOUND` |
| `getTransaction(id)` | `GET /card-transactions/{id}` | `TransactionDetail` | `TRANSACTION_NOT_FOUND` |
| `getUpcomingBilling()` | `GET /card-billing/upcoming` | `UpcomingBilling` | - |
| `suspendCard(cardId, accountPin)` | `POST /cards/{id}/suspend` | `CardStatusResult` | `CARD_NOT_FOUND`, `CARD_STATE_INVALID`, `ACCOUNT_PIN_MISMATCH`, `ACCOUNT_PIN_LOCKED`, `ACCOUNT_SERVICE_UNAVAILABLE` |
| `resumeCard(cardId, accountPin)` | `POST /cards/{id}/resume` | `CardStatusResult` | 위와 같음 |
| `reportLost(cardId, { reason, accountPin })` | `POST /cards/{id}/report-lost` | `CardStatusResult` | 위와 같음, `VALIDATION_FAILED` |
| `getCardLimit(cardId)` | `GET /cards/{id}/limit` | `CardLimit` | `CARD_NOT_FOUND`, `CARD_STATE_INVALID` |
| `listCardProducts()` | `GET /card-products` | `{ items: CardProduct[] }` | - |
| `getApplyEligibility()` | `GET /card-applications/eligibility` | `ApplyEligibility` | `MEMBER_SERVICE_UNAVAILABLE` |
| `applyCard(body, idempotencyKey)` | `POST /card-applications` | `CardApplicationResult` | `VALIDATION_FAILED`, `ACCOUNT_NOT_FOUND`, `APPLICANT_NOT_ELIGIBLE`, `CARD_COUNT_LIMIT_EXCEEDED`, `ACCOUNT_PIN_MISMATCH`, `ACCOUNT_PIN_LOCKED`, `IDEMPOTENCY_KEY_REUSED`, `ACCOUNT_SERVICE_UNAVAILABLE`, `MEMBER_SERVICE_UNAVAILABLE` |
| `checkTermination(cardId)` | `GET /cards/{id}/termination-check` | `TerminationCheck` | `CARD_NOT_FOUND`, `CARD_STATE_INVALID` |
| `terminateCard(cardId, body)` | `POST /cards/{id}/terminate` | `TerminateResult` | `VALIDATION_FAILED`, `CARD_STATE_INVALID`, `CARD_TERMINATE_BLOCKED_UNPAID`, 암호 오류 3종 |
| `listPaymentAccounts()` | `GET /accounts?purpose=card_payment` | `{ items: PaymentAccount[] }` | (계좌 담당 API. 카드 `cardApi`에 두되 계좌 담당 계약을 따른다) |

### 3.4 타입

```ts
export type CardType = 'credit' | 'debit'
export type CardStatus = 'active' | 'suspended' | 'lost' | 'terminated'
export type CardAction =
  | 'view_transactions' | 'view_limit' | 'suspend' | 'resume' | 'report_lost' | 'terminate'

export type PaymentAccount = { accountId: string; bankName: string; accountMasked: string }
export type CreditLimit = { total: number; used: number; remaining: number; usageRate: number }
export type DebitLimit = { perTx: number; perDay: number }

export type CardSummary = {
  id: string; name: string; type: CardType; numberMasked: string
  status: CardStatus; issuedAt: string; terminatedAt: string | null
}
export type CardListResponse = { items: CardSummary[]; terminatedCount: number }

export type CardDetail = {
  id: string; name: string; type: CardType; numberMasked: string; expiry: string
  status: CardStatus; issuedAt: string; paymentAccount: PaymentAccount
  paymentDay: number | null; limit: CreditLimit | null; debitLimit: DebitLimit | null
  suspendedAt: string | null; lostAt: string | null; lostReason: 'lost' | 'stolen' | null
  terminatedAt: string | null; availableActions: CardAction[]
}

export type CardStatusResult = {
  id: string; status: CardStatus
  suspendedAt: string | null; lostAt: string | null; lostReason: 'lost' | 'stolen' | null
}

export type TransactionKind = 'approval' | 'cancel'
export type TransactionItem = {
  id: string; cardId: string; cardName: string; cardType: CardType; cardNumberLast4: string
  occurredAt: string; merchant: string; amount: number; kind: TransactionKind
  originalId: string | null; installmentMonths: number
}
export type TransactionDetail = TransactionItem & {
  original: { id: string; occurredAt: string; merchant: string; amount: number } | null
}
export type TransactionListParams = {
  cardId?: string; from: string; to: string
  kind?: 'all' | 'approval' | 'cancel'; merchant?: string; limit?: number; cursor?: string
}
export type TransactionSummary = {
  approvalTotal: number; cancelTotal: number; netTotal: number; count: number
}
export type TransactionListResponse = {
  summary: TransactionSummary; items: TransactionItem[]; nextCursor: string | null
}

export type BillingItem = {
  kind: 'approval' | 'cancel' | 'installment'; occurredAt: string; merchant: string; amount: number
  installment: { round: number; months: number } | null
}
export type BillingCard = {
  cardId: string; cardName: string; status: 'active' | 'suspended' | 'lost'
  cardNumberLast4: string; amount: number
  usagePeriod: { from: string; to: string }; items: BillingItem[]
}
export type BillingPayment = {
  paymentDate: string; isCurrentMonth: boolean; paymentAccount: PaymentAccount
  amount: number; balance: number | null
  balanceStatus: 'ok' | 'insufficient' | 'unavailable'; shortfall: number | null
  cards: BillingCard[]
}
export type UpcomingBilling = {
  asOf: string; hasCreditCard: boolean; thisMonthTotal: number
  nextPaymentDate: string | null; daysUntilPayment: number | null; payments: BillingPayment[]
}

export type CardLimit = {
  cardId: string; type: CardType; status: CardStatus
  credit: CreditLimit | null; debit: DebitLimit | null
}

export type CardProduct = { id: string; type: CardType; name: string; description: string }
export type ApplyEligibility = {
  types: Record<CardType, {
    available: boolean; reason: 'AGE_UNDER_19' | 'COUNT_EXCEEDED' | null
    currentCount: number; maxCount: number
  }>
}
export type IncomeRange = 'none' | 'lt_10m' | '10m_20m' | '20m_40m' | '40m_70m' | 'gte_70m'
export type CardApplicationRequest = {
  type: CardType; productId: string; paymentAccountId: string
  paymentDay?: number; incomeRange?: IncomeRange; cardPin: string
  recipient: string; phone: string; address: { line1: string; line2?: string }
  agreements: { cardTerms: boolean; privacy: boolean; creditInquiry?: boolean }
  accountPin: string
}
export type IssuedCard = {
  id: string; name: string; type: CardType; numberMasked: string; expiry: string
  status: 'active'; issuedAt: string; paymentAccount: PaymentAccount
  paymentDay: number | null; limit: CreditLimit | null; debitLimit: DebitLimit | null
}
export type CardApplicationResult = {
  id: string; type: CardType; status: 'approved' | 'rejected'; requestedAt: string
  grantedLimit: number | null; rejectReason: 'INCOME_INSUFFICIENT' | null
  card: IssuedCard | null
  estimatedDeliveryBusinessDays: { min: number; max: number } | null
}

export type TerminationCheck = {
  cardId: string; canTerminate: boolean; blockReason: 'UNPAID_BALANCE' | null
  unpaidAmount: number; firstDueDate: string | null
}
export type TerminateReason = 'unused' | 'benefit_complaint' | 'other_card' | 'lost_cleanup' | 'other'
export type TerminateRequest = { reason?: TerminateReason | null; acknowledged: true; accountPin: string }
export type TerminateResult = { id: string; status: 'terminated'; terminatedAt: string }
```

## 4. 인증 틀

로그인·회원 기능은 `docs/roles.md`에 담당자가 없다. 카드 프론트가 **필요로 하는 최소한의 계약**만 정한다. 구현은 로그인 담당이 정해지면 그쪽에서 한다.

- `useAuth(): { status: 'loading' | 'authenticated' | 'anonymous'; member: { memberId: string; name: string } | null }`
- `<RequireAuth />` (라우트 가드)
  - `anonymous`: `/login?redirect=<현재 경로+쿼리를 URL 인코딩>` 으로 `replace` 이동
  - `loading`: 로딩 표시
  - 가드는 `card` 라우트 한 곳에 건다.
- `/login`: `redirect` 쿼리가 있으면 로그인 성공 뒤 그 경로로 이동한다. **같은 출처의 경로만 허용**한다 (`/`로 시작하고 `//`로 시작하지 않을 때만). 다르면 `/`로 이동.
- `401 AUTH_REQUIRED`: `http.ts`가 `ApiError`로 던지고, 최상위 오류 처리기 한 곳이 같은 방식으로 `/login?redirect=`로 보낸다.
- 토큰 저장 위치는 로그인 담당이 정한다. 카드 코드는 `getAccessToken()` 함수 하나만 호출한다.
- 목업: `mock.setMember(null)`이면 비로그인이다 (모든 API가 `401`).

## 5. 서버 상태·캐시

서버 상태 라이브러리(TanStack Query 등)는 아직 설치하지 않았다. 설치하려면 팀 합의가 필요하다. 아래는 **라이브러리를 쓴다고 가정한 키 규칙**이다. 쓰지 않는다면 같은 키·무효화 규칙을 직접 구현한다.

### 5.1 조회 키

| 키 | 조회 | staleTime |
|----|------|:---------:|
| `['cards', { includeTerminated }]` | `listCards` | 0 |
| `['card', cardId]` | `getCard` | 0 |
| `['limit', cardId]` | `getCardLimit` | 0 |
| `['transactions', params]` | `listTransactions` (더 보기는 무한 목록) | 0 |
| `['transaction', id]` | `getTransaction` | 60초 |
| `['billing']` | `getUpcomingBilling` | 0 |
| `['eligibility']` | `getApplyEligibility` | 0 |
| `['products']` | `listCardProducts` | 5분 |
| `['paymentAccounts']` | `listPaymentAccounts` | 0 |
| `['termination', cardId]` | `checkTermination` | 0 |

staleTime 0은 화면에 들어올 때마다 다시 조회한다는 뜻이다. 카드 상태·한도·청구는 항상 서버 값을 따른다.

### 5.2 쓰기 후 무효화

| 쓰기 | 무효화할 키 |
|------|-------------|
| `suspendCard`, `resumeCard`, `reportLost` | `['cards']`, `['card', id]`, `['limit', id]`, `['billing']` |
| `terminateCard` | `['cards']`, `['card', id]`, `['limit', id]`, `['billing']`, `['eligibility']`, `['termination', id]` |
| `applyCard` (승인) | `['cards']`, `['eligibility']` |

### 5.3 요청 경합

- 필터가 바뀌어 새 요청이 나가면 이전 요청은 취소(`AbortController`)하거나 결과를 버린다. 마지막 요청의 응답만 화면에 반영한다 (02).
- 쓰기 요청은 중복 클릭을 막으려고 진행 중에는 버튼을 비활성화한다.

## 6. 목업 서버

### 6.1 구조와 전환

- `mock/fixtures.ts`: [00 10절 기준 데이터](../../card/00-api-common.md#10-목업-데이터-기준표)를 코드로 옮긴 것
- `mock/mockServer.ts`: 3.3절 함수와 **같은 시그니처**로 구현. 서버와 **같은 검사 순서**([00 1.5](../../card/00-api-common.md#15-서버-처리-순서))로 같은 오류를 던진다
- `mock/control.ts`: 개발자용 제어 함수 (`window.__cardMock`으로 노출)
- 환경 변수 `VITE_USE_MOCK`(기본 `true`)으로 목업과 실제 API를 바꾼다.
- 목업이 구현해야 하는 규칙: 상태 전이([00 5절](../../card/00-api-common.md#5-카드-상태-전이-서버-기준)), 계좌 암호 카운터(계좌 단위, 5회 → 300초 잠금), 멱등성(`201`만 저장·회원별 키·24시간), 3장 제한, 청구 주기 계산(`lib/cycles.ts`)

### 6.2 시계

- 목업의 "오늘"은 `clock.ts`의 `now()` 하나에서 가져온다. 기본값은 `2026-11-04T09:43:00+09:00`.
- **고정 시계가 기본이 아니다.** 설정한 시각에서 **실제 시간과 같은 속도로 흐른다.** 시계가 멈춰 있으면 암호 잠금 카운트다운이 끝나도 목업 서버의 잠금이 풀리지 않아 계속 `429`가 되기 때문이다.
- 테스트에서는 멈춘 시계를 쓴다: `mock.setNow(iso, { frozen: true })`, 시간을 보내려면 `mock.advance(seconds)`.

### 6.3 제어 함수

| 함수 | 설명 |
|------|------|
| `mock.setNow(iso, { frozen? })` | 시계를 그 시각으로 맞춘다. `frozen: true`면 멈춘다 (기본은 흐름) |
| `mock.advance(seconds)` | 시계를 앞으로 보낸다 |
| `mock.setMember(id \| null)` | 로그인 회원을 바꾼다. `null`은 비로그인 |
| `mock.reset()` | 모든 데이터와 시계를 기준 상태로 되돌린다 |
| `mock.setLatency(ms)` | 모든 응답을 지연시킨다 (로딩 표시 확인용) |
| `mock.failNext(kind, { times? })` | 다음 요청(기본 1건)에 장애를 넣는다 |

`failNext`의 `kind`

| kind | 서버 상태 | 클라이언트가 받는 것 |
|------|-----------|----------------------|
| `network` | 처리하지 않음 | `NETWORK_ERROR` |
| `lostResponse` | **처리는 완료됨** | `TIMEOUT` (응답만 유실) |
| `server500` | 처리하지 않음 | `500 INTERNAL_ERROR` |
| `accountServiceDown` | 처리하지 않음, 오류 횟수 변화 없음 | `503 ACCOUNT_SERVICE_UNAVAILABLE` (암호 검증·계좌 조회) |
| `memberServiceDown` | 처리하지 않음 | `503 MEMBER_SERVICE_UNAVAILABLE` |
| `balanceLookupFail` | 정상 | 청구 조회의 잔액만 `balanceStatus: "unavailable"` |

`lostResponse`와 `network`를 나눠 둔 것은 04 T33, 06 T51, 07 T38처럼 "처리는 됐는데 응답만 못 받은" 경우와 "처리 안 됨"을 따로 확인하기 위해서다.

### 6.4 화면 상태 재현용 추가 회원

00 10절의 기준 데이터만으로는 아래 화면 상태를 만들 수 없어 목업에 회원을 더 둔다. **UI 확인 전용**이며 API 테스트 기준(00 10절)에는 포함하지 않는다. 계좌 암호는 모두 `1234`.

| 회원 | 보유 | 확인할 화면 |
|------|------|-------------|
| `member_005` | `card_501` (체크, terminated)만 | 01: 기본 목록이 비고 "해지된 카드 보기"만 있는 상태 |
| `member_006` | `card_601` (체크, active), `acc_601`만 | 03: 체크카드만 있는 회원의 청구 화면 |
| `member_007` | `card_701` (신용, active, 한도 100,000, 결제 계좌 `acc_701`), 거래 `tx_701` (2026-10-20, 150,000, approval, 일시불) | 01·05: 이용 금액이 한도를 넘는 상태 (`used` 150,000, `remaining` 0, `usageRate` 100) |

분실 사유 `stolen` 표시는 `member_001`로 `card_002`를 `report-lost`(사유 `stolen`)하면 만들 수 있어 따로 두지 않는다.

## 7. `AccountPinDialog` 계약

정지·해제·분실 신고·카드 신청·해지가 모두 이 팝업으로 계좌 암호를 받는다 ([00 4.4](../../card/00-api-common.md#44-화면-규칙-암호-입력-팝업-공통)).

### 7.1 props

```ts
type AccountPinDialogProps = {
  accountId: string                                 // 잠금 공유 키
  account: { bankName: string; accountMasked: string } // 팝업에 표시
  title: string                                     // 예: "계좌 암호 입력"
  description?: string                              // 예: "일시정지를 진행하려면 결제 계좌의 암호를 입력해 주세요"
  confirmLabel: string                              // 예: "확인"
  onSubmit: (pin: string) => Promise<void>          // 서버 요청. 실패하면 ApiError를 던진다
  onSuccess: () => void                             // onSubmit이 성공하면 호출. 호출한 쪽이 팝업을 닫는다
  onError: (err: ApiError) => void                  // 계좌 암호 오류가 아닌 오류(상태 변경, 장애, 응답 없음 등)
  onClose: () => void                               // 사용자가 닫기
}
```

### 7.2 상태

| 상태 | 설명 | 확인 버튼 | 입력 |
|------|------|-----------|------|
| `idle` | 입력 대기 | 4자리일 때만 활성 | 가능 |
| `submitting` | `onSubmit` 진행 중 | 비활성 + "처리 중..." | 비활성 |
| `mismatch` | `ACCOUNT_PIN_MISMATCH` (`remainingAttempts` 표시) | `idle`과 같음 | 입력값 지운 뒤 가능 |
| `locked` | `ACCOUNT_PIN_LOCKED` (`retryAfterSeconds`로 카운트다운) | 비활성 | 비활성 |

### 7.3 동작

- `onSubmit`이 던지는 오류를 `code`로 나눈다.
  - `ACCOUNT_PIN_MISMATCH` → `mismatch` 상태. 문구 "계좌 암호가 올바르지 않습니다. (남은 시도 N회)"
  - `ACCOUNT_PIN_LOCKED` → `locked` 상태. 문구 "계좌 암호를 5회 연속 틀려 M분 S초 뒤에 다시 입력할 수 있습니다."
  - 그 밖의 `ApiError`(`CARD_STATE_INVALID`, `CARD_TERMINATE_BLOCKED_UNPAID`, `ACCOUNT_SERVICE_UNAVAILABLE`, `NETWORK_ERROR`, `TIMEOUT` 등) → 팝업을 닫고 `onError(err)`를 호출한다. 이 오류를 어떻게 보여줄지는 호출한 화면이 정한다 (기능 문서의 예외·오류 처리 표).
- **요청을 보낸 직후(성공이든 실패든) 입력값을 지운다.**
- **처리 중(`submitting`)에는 닫을 수 없다.** Esc와 바깥 클릭을 무시한다. 그 밖의 상태에서는 닫을 수 있다.
- **잠금 공유**: 같은 계좌의 잠금이 풀릴 때까지는 어느 팝업에서든 `locked` 상태로 열린다. 구현은 모듈 수준 `Map<accountId, 잠금 끝 시각>`이다. 시각은 **`performance.now()` 기준 경과 시간**으로 센다 (사용자가 기기 시계를 바꿔도 영향이 없게). 새로고침하면 이 값은 사라지고, 그 뒤 처음 제출할 때 서버가 `429`로 알려준다 (서버가 기준이다).
- 카운트다운은 1초마다 줄이고, 0이 되면 `idle`로 돌아간다.

### 7.4 접근성

- `role="dialog"`, `aria-modal="true"`, 제목은 `aria-labelledby`
- 열릴 때 입력창에 포커스, 닫을 때 팝업을 연 버튼으로 포커스 복귀. 팝업 안에서 포커스가 순환한다 (포커스 트랩)
- 오류·잠금 문구는 `aria-live="polite"` 영역에 둔다. 카운트다운은 매초 읽지 않고 **시작할 때와 끝날 때만** 알린다.
- 입력은 `type="password"`, `inputMode="numeric"`, `maxLength=4`, `autoComplete="off"`

## 8. 폼 규칙

### 8.1 02 이용내역 필터와 주소 쿼리

필터 상태는 주소의 쿼리와 동기화한다. 새로고침·뒤로 가기에서 같은 화면이 나와야 한다.

| 쿼리 | 값 | 기본 | 설명 |
|------|-----|------|------|
| `cardId` | 카드 ID | (없음 = 전체) | 카드 상세에서 올 때 채워진다 |
| `preset` | `this_month`, `1m`, `3m`, `custom` | `this_month` | 기간 버튼 |
| `from`, `to` | `YYYY-MM-DD` | - | `preset=custom`일 때만 쓴다. 다른 값이면 무시하고 `preset`으로 계산한다 |
| `kind` | `all`, `approval`, `cancel` | `all` | |
| `merchant` | 문자열 | (없음) | |

- 프리셋 계산 (오늘 = KST): `this_month` = 이번 달 1일 ~ 오늘, `1m` = 오늘의 1개월 전 같은 일자 ~ 오늘, `3m` = 3개월 전 ~ 오늘. 그 일자가 없으면 그 달의 마지막 날.
- 새로고침 후 어떤 기간 버튼이 선택됐는지 `preset`으로 복원한다.
- 직접 입력: `<input type="date">` 두 개. `max`는 오늘. **둘 다 유효하게 채워지면 자동 조회**하고, 입력 중에는(한쪽이 비었거나 규칙 위반) 조회하지 않는다. 규칙 위반 문구는 02 문서의 표를 쓴다.
- 가맹점 검색: 입력 후 검색 버튼 또는 엔터로 조회한다.

### 8.2 06 신청 폼 컨트롤

| 필드 | 컨트롤 |
|------|--------|
| 카드 종류·상품 | 종류별 선택 카드(라디오). 불가능한 종류는 비활성화하고 이유 문구 |
| 결제 계좌 | 계좌 목록 라디오 (은행명 + 마스킹 번호) |
| 결제일 | `<select>` 1~28일, **기본 25일** |
| 연소득 구간 | 라디오 목록 (표시 문구는 06 문서) |
| 카드 비밀번호 | `type="password"` 두 칸(비밀번호, 확인), `inputMode="numeric"`, `maxLength=4` |
| 수령인 | 텍스트, `maxLength=20` |
| 연락처 | 숫자만 입력받고 **자동으로 하이픈을 넣는다** (`01012345678` → `010-1234-5678`) |
| 배송 주소 | 기본 주소 텍스트 `maxLength=100`, 상세 주소 텍스트 `maxLength=100` |
| 약관 | 체크박스 + 전체 동의. 약관 본문은 펼침 영역 (내용은 목업 문구) |

- 검증 시점: 필드를 벗어날 때(blur) 그 필드, **다음 단계 버튼**을 누를 때 단계 전체. 오류는 입력 바로 아래에 보여준다.
- 검증 규칙은 `validateApplyStep(step, draft)` 같은 함수 하나로 만들고 단계 이동과 제출 전 검사가 같은 함수를 쓴다.

### 8.3 07 해지 폼

- 해지 사유: 라디오 5개 (선택 해제 가능). 분실 카드는 `lost_cleanup`이 미리 선택된다 (바꿀 수 있음).
- 유의사항 확인: 체크박스. 체크하기 전에는 **해지하기** 버튼이 비활성화된다.

### 8.4 오류 사유 → 문구

서버 `fields[].reason`과 클라이언트 검증이 같은 문구를 쓴다. (02의 날짜·검색어 문구는 02 문서의 표를 따른다.)

| reason | 필드 | 문구 |
|--------|------|------|
| `REQUIRED` | 공통 | 필수 입력 항목입니다 |
| `INVALID_FORMAT` | `phone` | 휴대폰 번호 형식(010-0000-0000)을 확인해 주세요 |
| `INVALID_FORMAT` | `cardPin`, `accountPin` | 숫자 4자리를 입력해 주세요 |
| `OUT_OF_RANGE` | `paymentDay` | 결제일은 1일부터 28일까지 선택할 수 있습니다 |
| `TOO_LONG` | `recipient` | 20자 이하로 입력해 주세요 |
| `TOO_LONG` | `address.line1`, `address.line2` | 100자 이하로 입력해 주세요 |
| `PIN_TOO_SIMPLE` | `cardPin` | 같은 숫자나 연속된 숫자는 사용할 수 없습니다 |
| `MUST_BE_TRUE` | `agreements.*` | 필수 약관에 동의해 주세요 |
| `MUST_BE_TRUE` | `acknowledged` | 유의사항을 확인해 주세요 |
| `INVALID_ENUM` | `incomeRange`, `reason`, `productId` | 올바른 값을 선택해 주세요 |
| `PRODUCT_TYPE_MISMATCH` | `productId` | 선택한 상품과 카드 종류가 맞지 않습니다. 처음부터 다시 선택해 주세요 |
| `NOT_ALLOWED` | 모두 | 화면이 보내지 않는 값이라 일어나지 않는다. 오면 기본 오류 문구 |
| (클라이언트 검사) | 카드 비밀번호 확인 | 비밀번호가 일치하지 않습니다 |

## 9. 디자인 토큰·공통 UI (제안)

레퍼런스 이미지(`docs/references/card/`)는 금융상품 소개 화면뿐이라 **카드 화면의 와이어프레임·카드 모양 시안은 이 문서에 없다.** 디자인이 정해지면 따로 추가한다. 아래는 구현에 필요한 최소한의 공통 규칙이다.

- 상태 뱃지 색 (`index.css`의 `@theme`에 토큰으로 추가): 일시정지 `--color-status-suspended`(주황 계열), 분실 `--color-status-lost`(빨강 계열), 해지 `--color-status-terminated`(회색 계열), 경고 `--color-warning`(빨강 계열). **색만으로 구분하지 않고 뱃지 문구를 함께 쓴다.**
- `PageHeader` 공용 컴포넌트: 카드 하위 화면의 상단. 뒤로 가기 버튼 + 제목 + 햄버거. props: `title: string`, `backTo?: string`. (현재 `Header`는 로고와 햄버거만 있는 메인 화면용이다.)
- 표기: 금액 `1,234,000원`, 날짜 `2026.11.04`, 일시 `2026.11.04 09:43`, 이용 비율 `40.3%`(소수 첫째 자리까지 항상 표시), 유효기간 `06/30`, 취소·음수 금액 `-12,000원`.
- 레이아웃: 최대 폭 440px 고정(`Layout`이 이미 처리). 터치할 수 있는 요소는 높이 44px 이상.
- 접근성: 아코디언(청구 카드별 영역)은 `aria-expanded`, 막대(`UsageBar`)는 `role="progressbar"`와 `aria-valuenow`, 로딩·오류 문구는 `aria-live="polite"`.

## 10. 테스트 도구 (제안)

- 단위 테스트 도구(Vitest + Testing Library 등)는 아직 설치하지 않았다. 설치하려면 팀 합의가 필요하다.
- 우선 대상: `lib/cycles.ts`의 순수 함수 (03 T16~T19, T25~T27 / 05 T11~T12), `mockServer`가 만드는 API 시나리오 (기능 문서의 T-번호).
- UI 시나리오는 화면 확인(수동)으로 시작하고, 자동화가 필요해지면 그때 정한다.

## 11. 합의가 필요한 항목

| 항목 | 내용 |
|------|------|
| 로그인 담당 | `docs/roles.md`에 없다. `/login`, 토큰 저장, `members/me`를 누가 만드는지 (4절의 계약을 따를 것) |
| 서버 상태 라이브러리 | TanStack Query 설치 여부 (5절) |
| 테스트 도구 | Vitest 등 설치 여부 (10절) |
| 와이어프레임·카드 시안 | 디자인 담당·레퍼런스 확보 (9절) |
