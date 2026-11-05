# 2. 이용내역 조회

[← 카드 기획서 개요](README.md) · 경로: `/card/transactions`

## 목적

기간과 가맹점으로 카드 이용내역을 찾고, 승인과 취소를 구분해서 확인한다.

## 사용자 시나리오

- 이번 달에 쓴 내역을 전체 카드 기준으로 본다.
- 특정 카드만, 또는 특정 가맹점만 골라서 본다.
- 취소된 결제가 어떤 거래였는지 확인한다.

## 화면 구성

### 조회 조건 (상단)

| 조건 | 선택지 | 기본값 |
|------|--------|--------|
| 카드 | 전체 / 카드별 | 전체. 카드 상세에서 들어오면 그 카드 |
| 기간 | 이번 달, 1개월, 3개월, 직접 입력 | 이번 달 |
| 구분 | 전체 / 승인 / 취소 | 전체 |
| 가맹점 | 검색어 입력 (부분 일치) | 비어 있음 |

- 직접 입력은 시작일·종료일 두 칸이다. 둘 다 유효하게 채워지면 자동으로 조회한다 (별도 조회 버튼 없음).
- 조건을 바꾸면 목록이 바로 다시 조회된다. 가맹점 검색은 입력 후 검색 버튼(또는 엔터)으로 조회한다.

### 요약 (조건 아래)

- 조회된 내역의 **승인 합계**, **취소 합계**, **순 이용액**(승인 − 취소)을 보여준다.

### 내역 목록

- 날짜별로 묶어서 최신순으로 보여준다.
- 한 줄에 표시할 것:

| 항목 | 설명 |
|------|------|
| 일시 | `HH:mm` (날짜는 묶음 제목에) |
| 가맹점 | 가맹점명 |
| 카드 | 카드 이름 + 끝 4자리 (카드 필터가 "전체"일 때만) |
| 금액 | 승인은 `+` 없이 `12,000원`, 취소는 `-12,000원` |
| 구분 | 승인 / 취소 뱃지. 취소는 색을 달리한다 |
| 할부 | `cardType`이 `credit`인 승인 건만. `installmentMonths`가 0이면 `일시불`, 아니면 `3개월`처럼 표시. 체크카드와 취소 건은 표시하지 않음 |

- 취소 건을 누르면 원 승인 거래(날짜·금액)를 짧게 보여준다. 거래 상세 API(`GET /card-transactions/{id}`)의 `original`을 쓰며, 원 거래가 현재 조회 기간·페이지 밖에 있어도 보인다.
- 한 번에 20건을 보여주고, 더 있으면 "더 보기" 버튼으로 20건씩 추가한다.

## 기능 규칙

1. 승인과 취소는 별도 거래로 기록한다. 취소 거래는 `originalId`로 원 승인 거래를 가리킨다.
2. 순 이용액 = 승인 합계 − 취소 합계. 취소 금액은 원 승인 금액과 같다(부분 취소는 다루지 않는다).
3. 조회 기간은 최대 12개월이다. 12개월을 넘기면 입력을 막고 "최대 12개월까지 조회할 수 있습니다"를 보여준다.
4. 시작일이 종료일보다 늦으면 조회하지 않고 오류 문구를 보여준다. 종료일은 오늘을 넘길 수 없다.
5. 가맹점 검색은 대소문자를 구분하지 않고 공백은 앞뒤만 제거한다.
6. 기간 필터는 승인·취소 **발생 일시** 기준이다.
7. 일시정지·분실·해지 상태의 카드도 과거 내역은 조회된다. 카드 필터 선택지에는 해지된 카드도 포함하되 "(해지)"를 붙여 구분한다.

## 상태별 화면

| 상태 | 처리 |
|------|------|
| 로딩 | 목록 자리에 로딩 표시. 조건은 그대로 둔다 |
| 결과 없음 | "조건에 맞는 이용내역이 없습니다" 안내와 조건 초기화 버튼 |
| 불러오기 실패 | "이용내역을 불러오지 못했습니다" + 다시 시도 버튼 |

## 데이터

[README의 Transaction 모델](README.md#4-공통-데이터-모델)을 쓴다.

- 목업은 [00 10.4 기준 데이터](00-api-common.md#104-거래)를 그대로 쓴다.
- 체크카드 내역은 `installmentMonths`가 항상 0이다.
- 취소 거래는 일시불 승인에만 생긴다 ([공통 계산 기준 6.8](00-api-common.md#6-금액-계산-기준-공통)).

## API 명세

공통 규칙은 [00-api-common.md](00-api-common.md)를 따른다. 예시는 [목업 기준표](00-api-common.md#10-목업-데이터-기준표) 값이다.

### `GET /api/v1/card-transactions` — 이용내역 목록

| 쿼리 | 타입 | 필수 | 설명 |
|------|------|:----:|------|
| `cardId` | string | 아니오 | 없으면 내 모든 카드 (해지된 카드 포함) |
| `from` | `YYYY-MM-DD` | 예 | 시작일, 그날 00:00:00부터 포함 |
| `to` | `YYYY-MM-DD` | 예 | 종료일, 그날 23:59:59까지 포함 |
| `kind` | `all` \| `approval` \| `cancel` | 아니오 (기본 `all`) | 승인/취소 구분 |
| `merchant` | string | 아니오 | 가맹점 검색어. 앞뒤 공백 제거 후 대소문자 구분 없이 부분 일치. `%`, `_` 같은 문자는 그대로 글자로 취급. 비면 조건 없음 |
| `limit` | integer | 아니오 (기본 20) | 1~50 |
| `cursor` | string | 아니오 | 이전 응답의 `nextCursor` |

정렬: `occurredAt` 내림차순, 같으면 `id` 내림차순.

응답 `200` (`cardId=card_002`, `from=2026-10-01`, `to=2026-10-31`)

```json
{
  "summary": { "approvalTotal": 912000, "cancelTotal": 12000, "netTotal": 900000, "count": 4 },
  "items": [
    { "id": "tx_206", "cardId": "card_002", "cardName": "AIM 신용카드", "cardType": "credit", "cardNumberLast4": "2222",
      "occurredAt": "2026-10-30T19:30:00+09:00", "merchant": "현대백화점", "amount": 600000,
      "kind": "approval", "originalId": null, "installmentMonths": 2 },
    { "id": "tx_204", "cardId": "card_002", "cardName": "AIM 신용카드", "cardType": "credit", "cardNumberLast4": "2222",
      "occurredAt": "2026-10-22T10:15:00+09:00", "merchant": "스타벅스 강남점", "amount": 12000,
      "kind": "cancel", "originalId": "tx_203", "installmentMonths": 0 },
    { "id": "tx_203", "cardId": "card_002", "cardName": "AIM 신용카드", "cardType": "credit", "cardNumberLast4": "2222",
      "occurredAt": "2026-10-18T09:05:00+09:00", "merchant": "스타벅스 강남점", "amount": 12000,
      "kind": "approval", "originalId": null, "installmentMonths": 0 },
    { "id": "tx_202", "cardId": "card_002", "cardName": "AIM 신용카드", "cardType": "credit", "cardNumberLast4": "2222",
      "occurredAt": "2026-10-05T12:20:00+09:00", "merchant": "쿠팡", "amount": 300000,
      "kind": "approval", "originalId": null, "installmentMonths": 0 }
  ],
  "nextCursor": null
}
```

- `summary`는 **조건에 맞는 전체 거래** 기준이다. 어느 페이지를 요청해도 같은 값이다.
  - `approvalTotal`: 승인 금액 합 (할부 승인도 전체 금액)
  - `cancelTotal`: 취소 금액 합
  - `netTotal` = `approvalTotal` − `cancelTotal`. **음수가 될 수 있다** (예: 취소만 조회하면 `-12000`).
  - `count`: 조건에 맞는 거래 수
- 항목의 `cardType`(`credit` / `debit`)은 할부 표시 여부를 정하는 데 쓴다.
- 항목의 `amount`는 항상 양수다. 화면에서 `kind`가 `cancel`이면 `-`를 붙여 보여준다.

### `GET /api/v1/card-transactions/{transactionId}` — 거래 상세

취소 거래는 `original`(원 승인 거래 요약)을 함께 내려준다. 승인 거래는 `original: null`.

```json
{
  "id": "tx_204", "cardId": "card_002", "cardName": "AIM 신용카드", "cardType": "credit", "cardNumberLast4": "2222",
  "occurredAt": "2026-10-22T10:15:00+09:00", "merchant": "스타벅스 강남점", "amount": 12000,
  "kind": "cancel", "originalId": "tx_203", "installmentMonths": 0,
  "original": { "id": "tx_203", "occurredAt": "2026-10-18T09:05:00+09:00", "merchant": "스타벅스 강남점", "amount": 12000 }
}
```

### 입력 검증

| 필드 | 규칙 | 위반 시 `reason` |
|------|------|------------------|
| `from`, `to` | 필수, `YYYY-MM-DD` 형식의 실제 있는 날짜 | `REQUIRED`, `INVALID_FORMAT` |
| `from` ≤ `to` | 시작일이 종료일보다 늦으면 안 됨 | `FROM_AFTER_TO` |
| `to` ≤ 오늘 | 종료일은 오늘(KST)을 넘길 수 없음 | `TO_IN_FUTURE` |
| 기간 | `from` ≥ (`to` − 12개월, 같은 일자). 예: `to=2026-11-04`이면 `from`은 `2025-11-04` 이후 | `PERIOD_TOO_LONG` |
| `kind` | `all`, `approval`, `cancel` 중 하나 | `INVALID_ENUM` |
| `merchant` | 공백 제거 후 50자 이하 | `TOO_LONG` |
| `limit` | 1~50 정수 | `OUT_OF_RANGE`, `INVALID_FORMAT` |

### 오류

| HTTP | code | 언제 |
|:----:|------|------|
| 400 | `VALIDATION_FAILED` | 위 검증 실패 (`details.fields`에 필드별 사유, 여러 개면 모두 담음) |
| 400 | `INVALID_CURSOR` | 커서가 깨졌거나, 이전 요청과 조회 조건(카드·기간·구분·가맹점)이 다름 |
| 401 | `AUTH_REQUIRED` | 토큰 없음·만료 |
| 404 | `CARD_NOT_FOUND` | `cardId`가 없거나 남의 카드 |
| 404 | `TRANSACTION_NOT_FOUND` | 거래 상세에서 없는 거래이거나 남의 거래 |

## 예외·오류 처리

| 상황 | API 결과 | 화면 동작 |
|------|----------|-----------|
| 직접 입력에서 시작일 또는 종료일을 비움 | (요청 안 보냄) | 조회하지 않고 이전 결과를 유지 (둘 다 유효하게 채워지면 자동 조회) |
| 시작일 > 종료일, 종료일이 미래, 12개월 초과 | `400` (클라이언트가 먼저 막는 것과 같은 규칙) | 해당 입력 아래에 사유 문구 표시, 목록은 이전 결과 유지 |
| 조건을 빠르게 연달아 바꿈 | 요청이 겹침 | **마지막 요청의 응답만** 화면에 반영하고 이전 요청 결과는 버림 |
| "더 보기" 도중 오류 | `5xx` 또는 네트워크 오류 | 이미 보이는 목록은 그대로 두고 목록 아래에 "더 불러오지 못했습니다 · 다시 시도" |
| 조건을 바꾼 뒤 이전 커서로 요청 | `400 INVALID_CURSOR` | 커서를 버리고 첫 페이지부터 다시 조회 (조건 변경 시 항상 커서 초기화하므로 정상 흐름에서는 발생하지 않음) |
| `cardId`를 주소로 조작 | `404 CARD_NOT_FOUND` | 카드 필터를 "전체"로 되돌리고 "카드를 찾을 수 없어 전체 카드로 조회합니다" 안내 |
| 결과 0건 | `200`, `items: []`, `summary` 모두 0 | "조건에 맞는 이용내역이 없습니다" + 조건 초기화 버튼 |
| 취소 거래 상세에서 `original`이 `null` | (데이터 불일치) | "원 거래 정보를 찾을 수 없습니다" 표시, 오류로 처리하지 않음 |
| 해지된 카드 선택 | `200` | 카드 필터 목록에 "(해지)"를 붙여 보여주고 정상 조회 |
| 서버 오류·10초 초과 | `5xx` | "이용내역을 불러오지 못했습니다" + 다시 시도, 조건은 유지 |

필드 사유 → 화면 문구

| reason | 문구 |
|--------|------|
| `FROM_AFTER_TO` | 시작일이 종료일보다 늦을 수 없습니다 |
| `TO_IN_FUTURE` | 종료일은 오늘을 넘길 수 없습니다 |
| `PERIOD_TOO_LONG` | 최대 12개월까지 조회할 수 있습니다 |
| `INVALID_FORMAT` | 날짜 형식을 확인해 주세요 |
| `TOO_LONG` | 가맹점 검색어는 50자까지 입력할 수 있습니다 |

## 프론트 구현 메모

- 라우트: `/card/transactions` (카드 상세에서 올 때 `?cardId=card_002`)
- 컴포넌트: `TransactionsPage`, `TransactionFilter`, `TransactionSummary`, `TransactionGroup`(날짜별), `TransactionRow`, `TransactionDetailSheet`
- 필터 상태는 주소의 쿼리스트링과 동기화해 새로고침·뒤로 가기에서 유지한다.
- 기간 버튼 계산(오늘 = KST): 이번 달 = 이번 달 1일 ~ 오늘, 1개월 = 오늘 − 1개월 ~ 오늘, 3개월 = 오늘 − 3개월 ~ 오늘.
- 날짜별 묶음 제목은 `occurredAt`의 KST 날짜 기준이다. 묶음 안 시간 표기는 `HH:mm`.
- 목록 합치기: "더 보기"는 같은 조건의 다음 페이지를 기존 목록 뒤에 붙인다. `id` 중복이 오면 한 번만 보여준다.

## 테스트 시나리오

표에 적지 않은 필수 쿼리(`from`, `to`)는 유효한 값(예: 2026-10-01 ~ 2026-10-31)이라고 본다.

| ID | 구분 | 조건 | 동작 | 기대 결과 |
|----|------|------|------|-----------|
| T01 | API | member_001 | `card_002`, 2026-10-01~10-31 조회 | 항목 4개, 순서 `tx_206`, `tx_204`, `tx_203`, `tx_202`, `summary` 912000 / 12000 / 900000 / 4, `nextCursor: null` |
| T02 | API | 위와 같음 | `kind=cancel` 추가 | 항목 1개(`tx_204`), `approvalTotal: 0`, `cancelTotal: 12000`, `netTotal: -12000` |
| T03 | API | 위와 같음 | `kind=approval` 추가 | 항목 3개, 취소 없음, `summary.cancelTotal: 0` |
| T04 | API | 위와 같음 | `merchant=스타벅스` 추가 | 항목 2개(`tx_204`, `tx_203`) |
| T05 | API | 위와 같음 | `merchant=  스타벅스  ` (앞뒤 공백) | T04와 같은 결과 |
| T06 | API | `card_002`, 2026-11-01~11-04 | `merchant=gs25` | 항목 1개(`tx_207`), 대소문자 무시 |
| T07 | API | `card_001`, 2026-10-01~10-31 | `limit=20` | 항목 20개(첫 항목 `tx_130`), `nextCursor` 있음, `summary.count: 30`, `approvalTotal: 465000` |
| T08 | API | T07의 `nextCursor` 사용 | 같은 조건으로 다음 페이지 | 항목 10개(마지막 `tx_101`), `nextCursor: null`, `summary` 동일 |
| T09 | API | `cardId` 없음, 2026-11-01~11-04 | 조회 | 항목 1개(`tx_207`) — 전체 카드 기준 |
| T10 | API | `card_005`(해지) | 기간 지정 조회 | `200`, `items: []`, `summary` 모두 0 |
| T11 | API | `to=2026-11-05` | 조회 | `400`, `TO_IN_FUTURE` |
| T12 | API | `from=2026-11-03`, `to=2026-11-02` | 조회 | `400`, `FROM_AFTER_TO` |
| T13 | API | `from=2025-11-03`, `to=2026-11-04` | 조회 | `400`, `PERIOD_TOO_LONG` |
| T14 | API | `from=2025-11-04`, `to=2026-11-04` | 조회 | `200` (정확히 12개월은 허용) |
| T15 | API | `from=2026-13-01` | 조회 | `400`, `INVALID_FORMAT` |
| T16 | API | `limit=0`, `limit=51` | 각각 조회 | `400`, `OUT_OF_RANGE` |
| T17 | API | `kind=refund` | 조회 | `400`, `INVALID_ENUM` |
| T18 | API | 51자 `merchant` | 조회 | `400`, `TOO_LONG` |
| T19 | API | 깨진 `cursor` 문자열 | 조회 | `400 INVALID_CURSOR` |
| T20 | API | T07의 `nextCursor`를 `kind=cancel`로 바꿔 사용 | 조회 | `400 INVALID_CURSOR` |
| T21 | API | `cardId=card_900`, `cardId=card_999` | 조회 | `404 CARD_NOT_FOUND` |
| T22 | API | `GET /card-transactions/tx_204` | 상세 | `original.id: tx_203` |
| T23 | API | `GET /card-transactions/tx_203` | 상세 | `original: null` |
| T24 | API | `GET /card-transactions/tx_999` | 상세 | `404 TRANSACTION_NOT_FOUND` |
| T25 | UI | member_001 | 이용내역 진입 (기본 조건) | 이번 달·전체 카드·전체 구분, `tx_207`만 표시 |
| T26 | UI | `card_002`, 10월 | 목록 확인 | 취소 건이 `-12,000원`과 취소 뱃지로 표시, 승인은 `12,000원` |
| T27 | UI | 같은 화면 | 취소 건 클릭 | 원 승인(2026.10.18, 12,000원) 표시 |
| T28 | UI | 필터 연속 변경 | 이전 요청이 나중에 도착 | 마지막으로 바꾼 조건의 결과만 보임 |
| T29 | UI | 목록 20건 표시 중 | "더 보기" 중 네트워크 끊김 | 기존 20건 유지, 아래에 재시도 문구 |
| T30 | UI | 결과 0건 | - | 빈 상태 문구와 조건 초기화 버튼, 요약 0원 |

## 완료 기준

- [ ] 기본 조회가 이번 달·전체 카드·전체 구분이다
- [ ] 승인 합계, 취소 합계, 순 이용액이 목록과 일치한다
- [ ] 취소 건이 `-` 금액과 취소 뱃지로 구분된다
- [ ] 12개월 초과·시작일 > 종료일 입력이 막힌다
- [ ] 가맹점 검색과 "더 보기"가 동작한다
- [ ] 카드 상세에서 들어오면 그 카드가 선택되어 있다
