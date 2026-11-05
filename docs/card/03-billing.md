# 3. 청구·결제 예정 금액

[← 카드 기획서 개요](README.md) · 경로: `/cards/billing`

## 목적

이번 달에 결제 계좌에서 빠져나갈 금액과 결제일을 미리 알려, 잔액 부족으로 인한 연체를 막는다.

## 사용자 시나리오

- 이번 달 카드 값이 얼마인지, 며칠에 빠져나가는지 확인한다.
- 결제될 계좌의 잔액이 모자라지 않은지 확인한다.
- 카드별로 어떤 이용이 청구되는지 본다.

## 적용 대상

- **신용카드만** 해당한다. 체크카드는 이용 즉시 계좌에서 출금되므로 청구가 없다.
- 체크카드만 가진 고객에게는 "체크카드는 이용 즉시 결제되어 청구 내역이 없습니다"를 보여준다.

## 화면 구성

### 요약 (상단)

| 항목 | 설명 |
|------|------|
| 이번 달 결제 예정액 | 오늘이 속한 달에 결제되는 청구액의 합계 (`thisMonthTotal`) |
| 결제일 | 가장 가까운 결제일 (`2026.11.25`) + `D-N` 표시 (당일이면 "오늘 결제") |

### 결제 예정 묶음 (결제일·결제 계좌별)

- 결제일과 결제 계좌가 같은 카드끼리 한 묶음이다. 묶음 머리에 결제일, 결제 계좌(은행명 + 마스킹 번호), 묶음 청구액을 보여준다.
- 이번 달 결제 묶음(`isCurrentMonth: true`)은 요약 아래에, 다음 달 이후 묶음은 "다음 결제 예정" 제목 아래에 따로 보여준다.
- **잔액 안내**는 묶음 머리 바로 아래에 보여준다. 결제 계좌 잔액이 묶음 청구액보다 적으면 경고 문구를 보여주고, 충분하면 아무 문구도 보여주지 않는다.
  - 문구 예: "결제 계좌 잔액이 부족합니다. 부족 금액 120,000원"

### 카드별 청구 내역

- 카드마다 접을 수 있는 영역 하나:
  - 헤더: 카드 이름, 상태 뱃지(일시정지·분실일 때), 끝 4자리, 청구액
  - 펼치면: 청구에 포함된 이용 건 목록 (일시, 가맹점, 청구 금액, 일시불/할부 회차)
- 취소 건은 `-` 금액으로 목록에 함께 보여준다.

## 기능 규칙 (목업 단순화 규칙)

1. **이용기간**: 전월 1일 ~ 전월 말일. 결제일에 이 기간의 이용분을 청구한다.
2. **결제일**: 카드별 `paymentDay` (1~28일, 신청 시 정하며 기본 25일). 이번 달 결제일이 이미 지났으면 다음 달 결제일을 "다음 결제 예정"으로 보여준다.
3. **일시불**: 이용기간 안의 승인 − 취소를 그대로 청구한다.
4. **할부**: 승인 금액 ÷ 개월 수를 매월 청구한다. 1원 미만(소수점)은 버리고, 마지막 회차에 남은 금액을 더한다 (예: 1,000,000원 3개월 → 333,333 / 333,333 / 333,334). 카드별 영역에는 `2/3회차`처럼 회차를 표시한다.
5. **취소**: 결제일 당일까지 이루어진 취소는 원 승인과 같은 청구에서 차감한다. 이미 결제된 건의 취소(결제일 다음 날 이후)는 취소가 일어난 달의 다음 결제일 청구에서 차감한다. 기준은 [공통 6.2](00-api-common.md#62-거래가-속하는-결제일)다.
6. **청구액이 0원**이면 "이번 달 결제 예정 금액이 없습니다"를 보여준다.
7. **잔액 비교**: 같은 결제 계좌로 같은 날 결제되는 카드가 둘 이상이면 청구액을 합산해서 잔액과 비교한다.
8. 일시정지·분실 카드도 이미 쌓인 이용분은 계속 청구된다.
9. 해지된 카드는 미결제 금액이 0원일 때만 해지되므로 청구 대상에서 제외한다.

## 상태별 화면

| 상태 | 처리 |
|------|------|
| 로딩 | 요약·카드별 영역에 로딩 표시 |
| 신용카드 없음 | 위 "적용 대상" 안내 문구 |
| 불러오기 실패 | "청구 정보를 불러오지 못했습니다" + 다시 시도 버튼 |
| 잔액 조회 실패 | 청구 정보는 보여주고, 묶음의 잔액 안내 자리에만 "잔액을 확인하지 못했습니다" 표시 |

## 데이터

- Card의 `paymentDay`, `paymentAccount`, Transaction의 `kind`·`amount`·`installmentMonths`·`occurredAt`으로 계산한다.
- 결제 계좌 잔액은 계좌 파트의 `get_account(user, account_id)`(같은 프로세스의 함수 호출)로 가져온다. 시드 잔액은 [공통.md 7.2](../common/공통.md)를 따른다.

## API 명세

공통 규칙은 [00-api-common.md](00-api-common.md), 청구액 계산은 [공통 계산 기준 6절](00-api-common.md#6-금액-계산-기준-공통)을 따른다. 예시는 [목업 기준표](00-api-common.md#10-목업-데이터-기준표) 값이다.

### `GET /api/card-billing/upcoming` — 결제 예정 조회

쿼리 없음. 서버가 오늘(KST)을 기준으로 계산한다.

**계산 요약**

1. 해지되지 않은 신용카드(정상·일시정지·분실)마다 다음 결제일([공통 6.6](00-api-common.md#66-다음-결제일), 오늘 이후 가장 가까운 결제일)을 구하고, 그 주기의 청구액 `B(P)`를 계산한다.
2. `B(P) = 0`인 카드는 결과에서 뺀다.
3. 결제일과 결제 계좌가 같은 카드끼리 묶어 한 덩어리(`payments[]`의 한 항목)로 만든다. 청구액은 합산한다.
4. 묶음의 결제 계좌 잔액을 계좌 서비스에서 가져와 비교한다.

응답 `200` (user1, 오늘 2026-11-04)

```json
{
  "asOf": "2026-11-04",
  "hasCreditCard": true,
  "thisMonthTotal": 945000,
  "nextPaymentDate": "2026-11-25",
  "daysUntilPayment": 21,
  "payments": [
    {
      "paymentDate": "2026-11-25",
      "isCurrentMonth": true,
      "paymentAccount": { "accountId": 1, "bankName": "AIM Bank", "accountMasked": "****1234" },
      "amount": 45000,
      "balance": 1500000,
      "balanceStatus": "ok",
      "shortfall": 0,
      "cards": [
        {
          "cardId": "card_004", "cardName": "AIM 신용카드", "status": "lost", "cardNumberLast4": "4444",
          "amount": 45000,
          "usagePeriod": { "from": "2026-10-01", "to": "2026-10-31" },
          "items": [
            { "kind": "approval", "occurredAt": "2026-10-15T20:00:00+09:00", "merchant": "올리브영", "amount": 45000, "installment": null }
          ]
        }
      ]
    },
    {
      "paymentDate": "2026-11-25",
      "isCurrentMonth": true,
      "paymentAccount": { "accountId": 2, "bankName": "AIM Bank", "accountMasked": "****5678" },
      "amount": 900000,
      "balance": 500000,
      "balanceStatus": "insufficient",
      "shortfall": 400000,
      "cards": [
        {
          "cardId": "card_002", "cardName": "AIM 신용카드", "status": "active", "cardNumberLast4": "2222",
          "amount": 900000,
          "usagePeriod": { "from": "2026-10-01", "to": "2026-10-31" },
          "items": [
            { "kind": "installment", "occurredAt": "2026-10-30T19:30:00+09:00", "merchant": "현대백화점", "amount": 300000, "installment": { "round": 1, "months": 2 } },
            { "kind": "cancel", "occurredAt": "2026-10-22T10:15:00+09:00", "merchant": "스타벅스 강남점", "amount": 12000, "installment": null },
            { "kind": "approval", "occurredAt": "2026-10-18T09:05:00+09:00", "merchant": "스타벅스 강남점", "amount": 12000, "installment": null },
            { "kind": "approval", "occurredAt": "2026-10-05T12:20:00+09:00", "merchant": "쿠팡", "amount": 300000, "installment": null },
            { "kind": "installment", "occurredAt": "2026-08-10T15:40:00+09:00", "merchant": "삼성전자", "amount": 300000, "installment": { "round": 3, "months": 3 } }
          ]
        }
      ]
    }
  ]
}
```

| 필드 | 설명 |
|------|------|
| `asOf` | 계산 기준 날짜 (오늘) |
| `hasCreditCard` | 해지되지 않은 신용카드가 하나라도 있는지. `false`면 `payments: []` |
| `thisMonthTotal` | `isCurrentMonth: true`인 묶음의 `amount` 합 |
| `nextPaymentDate` | `payments` 중 가장 빠른 `paymentDate`. 비어 있으면 `null` |
| `daysUntilPayment` | `nextPaymentDate` − `asOf` (일). 당일이면 `0`. `nextPaymentDate`가 `null`이면 `null` |
| `payments[]` | 결제일 → 결제 계좌 `accountId` 순 오름차순 |
| `payments[].isCurrentMonth` | `paymentDate`의 연·월이 `asOf`와 같은지 |
| `payments[].amount` | 묶음 청구액 합계 (카드별 `amount`의 합) |
| `payments[].balance` | 결제 계좌 잔액. 조회 실패 시 `null` |
| `payments[].balanceStatus` | `ok` (잔액 ≥ 청구액) / `insufficient` (잔액 < 청구액) / `unavailable` (잔액 조회 실패) |
| `payments[].shortfall` | `insufficient`일 때 `amount − balance`, `ok`이면 `0`, `unavailable`이면 `null` |
| `cards[].status` | 카드 상태 (`active`, `suspended`, `lost`). 화면에서 정지·분실 뱃지를 붙일 때 쓴다 |
| `cards[].usagePeriod` | 이 청구에 해당하는 이용기간 (결제일이 속한 달의 전월 1일 ~ 말일) |
| `cards[].items[]` | 청구에 포함된 내역. `occurredAt` 내림차순 |
| `items[].kind` | `approval` (일시불 승인), `cancel` (취소, 청구액에서 차감), `installment` (할부 회차) |
| `items[].installment` | `installment`일 때 `{ round, months }`, 그 외 `null`. 할부는 `occurredAt`이 원 승인 일시, `amount`가 그 회차 금액 |

### 오류

| HTTP | code | 언제 |
|:----:|------|------|
| 401 | `LOGIN_REQUIRED` / `SESSION_EXPIRED` | 로그인하지 않았거나 세션 만료 (`details` 없음) |
| 403 | `PIN_SETUP_REQUIRED` | 간편비밀번호를 아직 설정하지 않은 사용자 |
| 500 | `INTERNAL_ERROR` | 계산 중 서버 오류 |

계좌 서비스에서 잔액을 못 가져와도 오류로 돌려주지 않는다. 해당 묶음만 `balanceStatus: "unavailable"`로 내려준다.

## 예외·오류 처리

| 상황 | API 결과 | 화면 동작 |
|------|----------|-----------|
| 신용카드가 없음 (체크카드만 있거나 카드 0장) | `hasCreditCard: false` | "신용카드가 없습니다. 체크카드는 이용 즉시 결제되어 청구 내역이 없습니다" |
| 신용카드는 있지만 청구액이 모두 0원 | `hasCreditCard: true`, `payments: []` | "이번 달 결제 예정 금액이 없습니다" |
| 이번 달 결제일이 이미 지남 | 묶음의 `isCurrentMonth: false` | 요약은 "이번 달 결제 예정 금액이 없습니다". 아래 "다음 결제 예정" 영역에 해당 묶음을 보여줌 |
| 결제일 당일 | `daysUntilPayment: 0` | 결제일 옆에 `D-N` 대신 "오늘 결제" |
| 잔액 부족 | `balanceStatus: "insufficient"` | 묶음 위에 "결제 계좌 잔액이 부족합니다. 부족 금액 {shortfall}원" 경고 (색과 문구 둘 다 사용) |
| 잔액 조회 실패 | `balanceStatus: "unavailable"` | 청구 내역은 그대로 보여주고 잔액 영역만 "잔액을 확인하지 못했습니다" |
| 같은 날·같은 계좌로 카드 둘 이상 결제 | 한 묶음으로 합산 | 잔액 비교는 합산 금액으로 하고, 묶음 안에서 카드별로 나눠 보여줌 |
| 결제 계좌가 서로 다른 카드들 | 묶음이 계좌별로 나뉨 | 계좌마다 따로 표시 |
| 취소가 승인보다 커서 청구액이 음수 | 해당 카드 `amount: 0` (카드 제외) | 표시하지 않음. 이월 없음 |
| 일시정지·분실 카드의 청구 | 정상 포함 | 카드 이름 옆에 상태 뱃지 |
| 서버 오류·10초 초과 | `5xx` | "청구 정보를 불러오지 못했습니다" + 다시 시도 |

## 프론트 구현 메모

- 라우트: `/cards/billing`
- 컴포넌트: `BillingPage`, `BillingSummary`, `PaymentGroup`(묶음), `BalanceAlert`, `BillingCardAccordion`, `BillingItemRow`
- D-day 표시: `daysUntilPayment`가 `0`이면 "오늘 결제", 아니면 `D-{n}`. 프론트에서 날짜 계산을 다시 하지 않고 응답 값을 쓴다.
- 카드별 영역은 접힌 상태로 시작하고, 접힌 헤더에 카드 이름·끝 4자리·청구액을 보여준다.
- 금액 표시: 취소 항목은 `-12,000원`, 할부는 `2/3회차`처럼 `round/months`.

## 테스트 시나리오

| ID | 구분 | 조건 | 동작 | 기대 결과 |
|----|------|------|------|-----------|
| T01 | API | user1, 오늘 2026-11-04 | `GET /card-billing/upcoming` | `thisMonthTotal: 945000`, `nextPaymentDate: "2026-11-25"`, `daysUntilPayment: 21`, `payments` 2개 |
| T02 | API | 위와 같음 | `payments` 순서 확인 | 같은 날짜이므로 계좌 순서: 계좌 1(45,000) → 계좌 2(900,000) |
| T03 | API | 위와 같음 | 계좌 2 묶음 | `balance: 500000`, `balanceStatus: "insufficient"`, `shortfall: 400000` |
| T04 | API | 위와 같음 | 계좌 1 묶음 | `balance: 1500000`, `balanceStatus: "ok"`, `shortfall: 0` |
| T05 | API | 위와 같음 | `card_002` 항목 | 5개, 할부 `{ round: 1, months: 2 }`와 `{ round: 3, months: 3 }`, 취소 항목 `amount: 12000`, 합계 900,000 |
| T06 | API | 위와 같음 | `usagePeriod` | `2026-10-01` ~ `2026-10-31` |
| T07 | API | 위와 같음 | `card_003`(일시정지, 거래 없음) | 어느 묶음에도 없음 |
| T08 | API | 위와 같음 | `card_004`(분실) | 계좌 1 묶음에 포함, 45,000 |
| T09 | API | 시계 2026-11-25 (결제일 당일) | 조회 | 11-25 묶음이 그대로 있고 `daysUntilPayment: 0` |
| T10 | API | 시계 2026-11-26 | 조회 | `card_002`는 `2026-12-25`, 금액 308,000 (`isCurrentMonth: false`), `card_004`는 청구 없음, `thisMonthTotal: 0`, `nextPaymentDate: "2026-12-25"`, `daysUntilPayment: 29` |
| T11 | API | 시계 2026-11-26 | 계좌 2 묶음 | 잔액 500,000원 ≥ 청구액 308,000원이므로 `balanceStatus: "ok"`, `shortfall: 0` |
| T12 | API | 시계 2027-02-01 | 조회 | `hasCreditCard: true`, `payments: []`, `nextPaymentDate: null`, `daysUntilPayment: null` |
| T13 | API | user3 (S-07 완료 후) | 조회 | `hasCreditCard: false`, `payments: []` |
| T14 | API | 잔액 서비스 실패를 흉내 냄 | 조회 | `200`, 해당 묶음 `balance: null`, `balanceStatus: "unavailable"`, `shortfall: null` |
| T15 | API | 로그인 안 함 (세션 없음) | 조회 | `401 LOGIN_REQUIRED` |
| T16 | 계산 | 단위 테스트 | 1,000,000원 3개월 할부 회차 금액 | 333,333 / 333,333 / 333,334 |
| T17 | 계산 | 단위 테스트 | 승인 없이 취소만 있는 주기 (취소 12,000원) | `B(P) = 0` (음수 아님, 이월 없음) |
| T18 | 계산 | 단위 테스트 | 8월 10일 승인 3개월 할부, 결제일 25 | 회차 결제일 9-25, 10-25, 11-25 |
| T19 | 계산 | 단위 테스트 | 결제일 25, 오늘 2026-11-25 / 2026-11-26 | 카드의 다음 결제일이 각각 2026-11-25 / 2026-12-25 |
| T20 | UI | user1 | 화면 진입 | 요약 945,000원, "D-21", 잔액 부족 경고(부족 400,000원) |
| T21 | UI | user1 | `card_002` 영역 펼침 | 취소는 `-12,000원`, 할부는 `1/2회차`, `3/3회차` |
| T22 | UI | user3 (S-07 완료 후) | 화면 진입 | 신용카드 없음 안내 문구 |
| T23 | UI | 시계 2026-11-26 | 화면 진입 | 요약 "이번 달 결제 예정 금액이 없습니다", "다음 결제 예정"에 12-25 / 308,000원 |
| T24 | UI | 시계 2026-11-25 | 화면 진입 | "오늘 결제" 표시 |
| T25 | 계산 | 단위 테스트 (결제일 25) | 10월 30일 600,000원 일시불 승인 → 11월 2일 취소, 다른 이용 없음 | 취소 일자가 원 승인의 결제일(11-25) 이전이므로 11-25 주기에서 차감: `B(11-25) = 0`, `B(12-25) = 0` |
| T26 | 계산 | 단위 테스트 (결제일 25) | 9월 12일 120,000원 승인 → 11월 2일 취소, 다른 이용 없음 | `B(10-25) = 120,000` 그대로(이미 결제됨), 11-02 취소는 `c > 10-25`이므로 12-25 주기에서 차감: `B(12-25) = 0` (음수는 0, 이월 없음) |
| T27 | 계산 | 단위 테스트 (결제일 25) | 10월 5일 승인 → 취소 일자가 결제일 당일(11월 25일) | 당일은 `c ≤ P_a`이므로 11-25 주기에서 차감 |
| T28 | API | 위 T25 데이터를 목업에 넣음 | 11월 2일 기준 `GET /card-billing/upcoming` | 해당 카드는 `B = 0`이라 `payments`에 없음 |

## 완료 기준

- [ ] 결제 예정액 합계가 카드별 청구액의 합과 일치한다
- [ ] 결제일과 D-N이 맞게 표시된다 (이미 지난 결제일 처리 포함)
- [ ] 할부 건이 월 분할액과 회차로 표시된다
- [ ] 잔액이 부족하면 경고와 부족 금액이 보인다
- [ ] 체크카드만 있는 고객에게 안내 문구가 보인다
