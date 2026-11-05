# 1. 내 카드 목록·상세

[← 카드 기획서 개요](README.md) · 경로: `/cards` (목록), `/cards/:cardId` (상세)

## 목적

고객이 보유한 카드를 한눈에 보고, 카드 한 장의 종류·결제 계좌·한도를 확인한다. 다른 4개 기능으로 들어가는 출발점이다.

## 사용자 시나리오

- 카드 메뉴를 열면 내가 가진 카드가 모두 보인다.
- 카드를 누르면 그 카드의 상세가 나오고, 거기서 이용내역·정지/분실·한도 화면으로 이동한다.
- 신용카드인지 체크카드인지, 어느 계좌에서 결제되는지, 한도가 얼마인지 바로 알 수 있다.

## 화면 구성

### 목록 (`/cards`)

- 상단: 제목 "내 카드", 카드 장수 (예: 3장), **카드 신청** 버튼 (→ [06-issuance.md](06-issuance.md), `/cards/apply`). 해지된 카드는 장수에 포함하지 않는다 (분실 카드는 포함한다. 신청 가능 장수를 세는 기준([06](06-issuance.md))은 분실도 제외하므로 두 숫자가 다를 수 있다)
- 카드 목록 (세로 나열). 한 카드 항목에 표시할 것:
  - 카드 이름, 종류 뱃지(신용 / 체크), 번호 끝 4자리
  - 상태 뱃지: 일시정지, 분실, 해지 (정상이면 표시하지 않음)
- 정렬: 정상 → 일시정지 → 분실 순, 같은 상태는 발급일 최신순
- 해지된 카드는 기본 목록에서 숨긴다. 목록 아래 **해지된 카드 보기**를 누르면 해지 뱃지와 함께 펼쳐진다 (해지가 없으면 이 줄 자체를 숨김)
- 카드 항목을 누르면 상세로 이동

### 상세 (`/cards/:cardId`)

| 영역 | 내용 |
|------|------|
| 카드 요약 | 카드 이름, 종류, 마스킹 번호, 유효기간, 상태 뱃지, 발급일 |
| 결제 계좌 | 은행명, 마스킹 계좌 번호. 신용카드는 결제일(매월 N일)도 함께 표시 |
| 한도 | 신용: 총 한도 / 이용 금액 / 잔여 한도 / 이용 비율(막대). 체크: 1회 한도 / 1일 한도 |
| 바로가기 | 이용내역 보기, 일시정지·분실신고(또는 정지 해제), 한도 조회, 카드 해지 ([07-termination.md](07-termination.md)) 링크 |

- 한도 영역의 이용 금액·잔여 한도·이용 비율은 [공통 계산 기준 6.5](00-api-common.md#65-이용-금액잔여-한도-신용카드)로 계산한 값이며, [05-limit.md](05-limit.md)의 한도 조회와 항상 같다.
- 체크카드에는 결제일과 신용 한도가 없으므로 해당 줄을 숨긴다.
- 상태가 분실이면 바로가기는 이용내역 보기, 한도 조회, 카드 해지만 보여준다. 카드 요약 아래에는 안내 영역을 함께 보여준다: "분실 신고된 카드입니다", 신고 일시, 사유(분실 / 도난), "고객센터로 재발급을 신청해 주세요".
- 상태가 해지이면 바로가기는 이용내역 보기만 보여준다.

## 기능 규칙

1. 카드 번호는 끝 4자리만 노출한다. 유효기간은 보여주되 CVC는 어떤 곳에도 보여주지 않는다.
2. 카드 종류에 따라 상세의 한도 영역이 달라진다 (위 표 참고).
3. 상세에서 다른 화면으로 이동할 때 `cardId`를 함께 넘긴다.
4. 존재하지 않는 `cardId`로 열면 "카드를 찾을 수 없습니다" 안내와 목록으로 돌아가는 버튼을 보여준다.

## 상태별 화면

| 상태 | 처리 |
|------|------|
| 로딩 | 목록·상세 자리에 로딩 표시 |
| 카드 없음 | "보유한 카드가 없습니다" 안내와 **카드 신청** 버튼 |
| 불러오기 실패 | "카드 정보를 불러오지 못했습니다" + 다시 시도 버튼 |

## 데이터

[README의 Card 모델](README.md#4-공통-데이터-모델)을 그대로 쓴다.

- 목록: 카드 전체 배열
- 상세: 카드 1건. 이용 금액은 Transaction에서 계산한다.

## API 명세

공통 규칙(인증, 오류 형식, 값 형식)은 [00-api-common.md](00-api-common.md)를 따른다. 예시는 [목업 기준표](00-api-common.md#10-목업-데이터-기준표) 값이다.

### `GET /api/cards` — 카드 목록

| 쿼리 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `includeTerminated` | boolean | `false` | `true`면 해지된 카드를 목록 끝에 포함 |

- 정렬: 상태 순(`active` → `suspended` → `lost`), 같은 상태는 `issuedAt` 내림차순. 해지된 카드는 마지막에 `terminatedAt` 내림차순.
- `terminatedCount`: 해지된 카드의 총 수. `includeTerminated` 값과 관계없이 항상 내려준다 ("해지된 카드 보기" 표시 여부 판단용).

응답 `200` (`includeTerminated=false`, user1)

```json
{
  "items": [
    { "id": "card_002", "name": "AIM 신용카드", "type": "credit", "numberMasked": "****-****-****-2222", "status": "active", "issuedAt": "2025-06-01", "terminatedAt": null },
    { "id": "card_001", "name": "AIM 체크카드", "type": "debit", "numberMasked": "****-****-****-1111", "status": "active", "issuedAt": "2025-03-10", "terminatedAt": null },
    { "id": "card_003", "name": "AIM 신용카드", "type": "credit", "numberMasked": "****-****-****-3333", "status": "suspended", "issuedAt": "2025-09-20", "terminatedAt": null },
    { "id": "card_004", "name": "AIM 신용카드", "type": "credit", "numberMasked": "****-****-****-4444", "status": "lost", "issuedAt": "2026-01-05", "terminatedAt": null }
  ],
  "terminatedCount": 1
}
```

### `GET /api/cards/{cardId}` — 카드 상세

응답 `200` (신용카드 `card_002`)

```json
{
  "id": "card_002",
  "name": "AIM 신용카드",
  "type": "credit",
  "numberMasked": "****-****-****-2222",
  "expiry": "06/30",
  "status": "active",
  "issuedAt": "2025-06-01",
  "paymentAccount": { "accountId": 2, "bankName": "AIM Bank", "accountMasked": "****5678" },
  "paymentDay": 25,
  "limit": { "total": 3000000, "used": 1208000, "remaining": 1792000, "usageRate": 40.3 },
  "debitLimit": null,
  "suspendedAt": null,
  "lostAt": null,
  "lostReason": null,
  "terminatedAt": null,
  "availableActions": ["view_transactions", "view_limit", "suspend", "report_lost", "terminate"]
}
```

응답 `200` (체크카드 `card_001`): 위와 같은 필드이고 `paymentDay: null`, `limit: null`, `debitLimit: { "perTx": 1000000, "perDay": 3000000 }`.

| 필드 | 값이 있는 경우 | 아닌 경우 |
|------|----------------|-----------|
| `paymentDay`, `limit` | 신용카드 | `null` |
| `debitLimit` | 체크카드 | `null` |
| `suspendedAt` | 상태가 `suspended` | `null` |
| `lostAt`, `lostReason` (`lost` \| `stolen`) | 분실 신고한 카드 (이후 해지해도 유지) | `null` |
| `terminatedAt` | 상태가 `terminated` | `null` |

- `limit.used`·`remaining`·`usageRate`는 [공통 계산 기준 6.5](00-api-common.md#65-이용-금액잔여-한도-신용카드)로 계산한다. 화면의 막대는 `usageRate`를 그대로 쓰고 클라이언트가 다시 계산하지 않는다.
- `availableActions`는 [상태 전이 표](00-api-common.md#5-카드-상태-전이-서버-기준) 그대로다. 프론트는 이 배열에 있는 바로가기만 보여준다.
- 해지된 카드도 상세는 `200`이다 (`availableActions`는 `["view_transactions"]`).

### 오류

| HTTP | code | 언제 |
|:----:|------|------|
| 400 | `VALIDATION_FAILED` | `includeTerminated`가 `true`/`false`가 아님 (`reason: INVALID_FORMAT`) |
| 401 | `LOGIN_REQUIRED` / `SESSION_EXPIRED` | 로그인하지 않았거나 세션 만료 (`details` 없음) |
| 403 | `PIN_SETUP_REQUIRED` | 간편비밀번호를 아직 설정하지 않은 사용자 |
| 404 | `CARD_NOT_FOUND` | 없는 카드이거나 남의 카드 |

## 예외·오류 처리

| 상황 | API 결과 | 화면 동작 |
|------|----------|-----------|
| 로그인 안 됨·세션 만료 | `401 LOGIN_REQUIRED` / `SESSION_EXPIRED` | `/login?next=<원래 경로>`로 이동, 로그인 후 돌아옴 |
| 간편비밀번호 미설정 | `403 PIN_SETUP_REQUIRED` | 간편비밀번호 설정 화면(S-07)으로 이동 |
| 없는 카드, 남의 카드, 주소를 직접 고쳐 접근 | `404 CARD_NOT_FOUND` | "카드를 찾을 수 없습니다" + 목록으로 버튼 |
| 보유 카드 0장 | `200`, `items: []` | 빈 상태 + **카드 신청** 버튼 |
| 해지된 카드만 있음 | `items: []`, `terminatedCount > 0` | 빈 상태 + 카드 신청 버튼 + "해지된 카드 보기" |
| 서버 오류·네트워크 오류·10초 초과 | `5xx` 또는 없음 | "카드 정보를 불러오지 못했습니다" + 다시 시도 |
| 다른 기기에서 상태가 바뀜 | 상세 응답이 최신 상태 | 상세는 항상 서버 값을 따른다. 목록은 화면에 다시 들어올 때마다 재조회 |
| 정지·분실·해지 처리 직후 목록 복귀 | - | 목록·상세 캐시를 무효화해 새 상태 표시 |
| 신용카드 이용 금액이 총 한도 이상(`used ≥ total`) | `remaining: 0`, `usageRate: 100` | 막대는 가득 채우고 "한도를 모두 사용했습니다" 표시 |

## 프론트 구현 메모

- 라우트: `/cards` (목록), `/cards/:cardId` (상세)
- 컴포넌트: `CardListPage`, `CardListItem`, `StatusBadge`, `TerminatedCardsToggle`, `CardDetailPage`, `CardSummary`, `PaymentInfo`, `LimitInfo`, `ActionLinks`
- 조회 캐시 키: `['cards', includeTerminated]`, `['card', cardId]`. 04·06·07의 쓰기가 성공하면 둘 다 무효화한다.
- "해지된 카드 보기"를 처음 누를 때 `includeTerminated=true`로 다시 조회하고, 응답의 해지 카드만 아래 영역에 나눠 그린다. 장수 표시는 해지 제외 개수다.
- 번호는 응답의 `numberMasked`를 그대로 쓴다. 클라이언트에서 직접 마스킹하지 않는다.

## 테스트 시나리오

| ID | 구분 | 조건 | 동작 | 기대 결과 |
|----|------|------|------|-----------|
| T01 | API | user1 | `GET /cards` | 순서 `card_002`, `card_001`, `card_003`, `card_004`, `terminatedCount: 1` |
| T02 | API | user1 | `GET /cards?includeTerminated=true` | 마지막 항목이 `card_005`, `terminatedAt` 값 있음 |
| T03 | API | user1 | `GET /cards/card_002` | `limit` 3,000,000 / 1,208,000 / 1,792,000 / `usageRate: 40.3`, `paymentDay: 25`, `debitLimit: null` |
| T04 | API | user1 | `GET /cards/card_001` | `paymentDay: null`, `limit: null`, `debitLimit` 있음 |
| T05 | API | user1 | `GET /cards/card_004` | `lostAt`, `lostReason: "lost"` 값 있음, `availableActions`는 `view_transactions`, `view_limit`, `terminate` |
| T06 | API | user1 | `GET /cards/card_005` | `200`, `availableActions: ["view_transactions"]` |
| T07 | API | user1 | `GET /cards/card_003` | `suspendedAt` 값 있음, `availableActions`에 `resume` 포함·`suspend` 없음 |
| T08 | API | user1 | `GET /cards/card_900` (남의 카드) | `404 CARD_NOT_FOUND` |
| T09 | API | user1 | `GET /cards/card_999` | `404 CARD_NOT_FOUND` |
| T10 | API | 로그인 안 함 (세션 없음) | `GET /cards` | `401 LOGIN_REQUIRED` |
| T11 | API | user1 | `GET /cards?includeTerminated=abc` | `400 VALIDATION_FAILED`, `INVALID_FORMAT` |
| T12 | API | user3 (S-07 완료 후) | `GET /cards` | `items: []`, `terminatedCount: 0` |
| T13 | UI | user1 | 목록 진입 | 장수 "4장", 카드 번호 끝 4자리만 표시, 해지 카드는 숨김 |
| T14 | UI | user1 | "해지된 카드 보기" 클릭 | `card_005`가 해지 뱃지와 함께 펼쳐짐 |
| T15 | UI | user1 | `card_002` 상세 | 한도 막대 40.3%, 결제일 "매월 25일", 정지·분실·한도·이용내역·해지 바로가기 |
| T16 | UI | user1 | `card_001` 상세 | 결제일·신용 한도 줄이 없음 |
| T17 | UI | user3 (S-07 완료 후) | 목록 진입 | 빈 상태와 카드 신청 버튼 |
| T18 | UI | 응답 지연 | 상세 진입 | 로딩 표시 후 값이 채워짐, 10초 넘으면 오류 상태 |
| T19 | UI | user1 | `card_004` (분실) 상세 | 안내 영역에 "분실 신고된 카드입니다", 신고 일시, 사유 "분실", 재발급 안내. 바로가기는 이용내역·한도 조회·카드 해지뿐 |
| T20 | API | user3 (간편비밀번호 미설정, S-07 전) | `GET /cards` | `403 PIN_SETUP_REQUIRED`, 화면은 S-07로 이동 |

## 완료 기준

- [ ] 신용·체크 카드가 섞인 목록이 정렬 규칙대로 보인다
- [ ] 신용카드 상세에 결제일과 3종 한도(총/이용/잔여)가 보인다
- [ ] 체크카드 상세에 결제일과 신용 한도가 보이지 않는다
- [ ] 분실 카드 상세에는 이용내역 보기, 한도 조회, 카드 해지만 보인다
- [ ] 해지된 카드는 기본 목록에서 숨겨지고, "해지된 카드 보기"에서 해지 뱃지와 함께 보인다
- [ ] 목록의 카드 신청 버튼이 신청 화면으로 이동한다
- [ ] 분실 카드 상세에 신고 일시·사유·재발급 안내가 보인다
- [ ] 상세의 한도 막대가 `usageRate` 값 그대로 그려진다
- [ ] 번호는 끝 4자리만 보인다
