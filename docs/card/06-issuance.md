# 6. 카드 신규 발급·신청

[← 카드 기획서 개요](README.md) · 경로: `/cards/apply` (진입: 내 카드 목록의 **카드 신청** 버튼)

## 목적

고객이 체크카드 또는 신용카드를 모바일 웹에서 직접 신청하고, 결과(발급 완료 / 거절)를 바로 확인한다.

## 범위

- 신청서 작성, 약관 동의, 본인 확인, 결과 확인까지.
- **범위 밖**: 카드 수령 후 사용 등록(활성화), 실물 배송 추적, 재발급, 신청 이력 목록. 신청이 끝나면 카드는 곧바로 "정상" 상태로 내 카드 목록에 추가된다 (목업 단순화).

## 사용자 시나리오

- 결제 계좌를 정해서 체크카드를 신청하고 바로 목록에서 확인한다.
- 소득 구간을 입력해 신용카드를 신청하고 부여된 한도를 확인한다.
- 신용카드 심사에서 거절되면 사유를 확인한다.

## 신청 흐름

```
1. 종류·상품 선택 → 2. 신청 정보 입력 → 3. 약관 동의 → 4. 확인·본인 확인 → 5. 결과
```

각 단계에서 이전 단계로 돌아갈 수 있고, 입력값은 유지된다. 맨 위에 현재 단계(1/5)를 보여준다.

### 1단계. 종류·상품 선택

| 항목 | 내용 |
|------|------|
| 카드 종류 | 체크카드 / 신용카드 |
| 상품 | 종류별 상품 카드(이름, 한 줄 설명). 목업은 체크 1종(AIM 체크카드), 신용 1종(AIM 신용카드)으로 고정 |

### 2단계. 신청 정보 입력

| 항목 | 체크 | 신용 | 규칙 |
|------|:----:|:----:|------|
| 결제 계좌 | O | O | 본인 명의 저축예금 계좌 중 선택 (끝 4자리 마스킹 표시). 정기예금·정기적금은 후보에 없다 |
| 결제일 | - | O | 1~28일 중 선택. 기본값 25일이 미리 선택되어 있다 |
| 연소득 구간 | - | O | 아래 표에서 선택 (필수) |
| 카드 비밀번호 | O | O | 숫자 4자리, 확인 입력 일치. `1111`처럼 모두 같은 숫자와 `1234`처럼 연속 숫자는 불가 |
| 수령인 | O | O | 필수 |
| 연락처 | O | O | 휴대폰 번호 형식 (`010-0000-0000`) |
| 배송 주소 | O | O | 기본 주소 필수, 상세 주소 선택. 직접 입력 (주소 검색은 범위 밖) |

- 결제 계좌가 하나도 없으면 "결제 계좌로 쓸 수 있는 계좌가 없습니다. 먼저 계좌를 개설해 주세요" 안내를 보여주고 신청을 진행하지 않는다.
- 카드 비밀번호는 형식·단순도만 검증하고 서버에 저장하지 않는다 (이 범위에서는 쓰는 곳이 없다). 화면에 다시 보여주지 않고 입력은 가린다.

### 3단계. 약관 동의

- **전체 동의** 체크 하나와 개별 항목:
  - 카드 이용 약관 (필수)
  - 개인정보 수집·이용 동의 (필수)
  - 신용정보 조회 동의 (필수, 신용카드만)
- 필수 항목을 모두 체크해야 다음 단계로 간다. 각 항목의 약관 보기는 펼침 영역으로 제공한다 (내용은 목업 문구).

### 4단계. 확인·본인 확인

- 신청 내용 요약: 카드 종류·상품, 결제 계좌, 결제일(신용), 수령인·연락처·주소. 카드 비밀번호는 표시하지 않는다.
- **신청하기** 버튼을 누르면 간편비밀번호 확인(S-08)이 열린다. 6자리 간편비밀번호를 입력해 통과하면 신청 요청이 전송된다. 이미 5분 안에 확인했으면 S-08 없이 바로 전송한다.

### 5단계. 결과

| 결과 | 보여주는 것 |
|------|-------------|
| 체크카드 발급 완료 | 카드 이름, 끝 4자리, 유효기간, 결제 계좌, "카드는 입력하신 주소로 3~5영업일 내 배송됩니다" |
| 신용카드 발급 완료 | 위 내용 + 결제일 + 부여된 신용 한도 |
| 신용카드 거절 | 거절 사유 문구, "다시 신청하기"(1단계로), "내 카드 보기" |
| 처리 실패(서버 오류) | "신청하지 못했습니다. 잠시 후 다시 시도해 주세요", 입력값 유지 |

완료 화면의 **내 카드 보기** 버튼은 `/cards`로 이동하고, 방금 만든 카드가 목록에 보인다.

## 기능 규칙

1. **로그인·본인 확인**: 로그인 상태에서만 열린다. 신청 확정(4단계) 직전에 6자리 **간편비밀번호**를 5분 안에 확인한 상태여야 한다 ([공통 4절](00-api-common.md#4-본인-재확인-간편비밀번호)). 확인하지 않았거나 5분이 지났으면 `403 PIN_VERIFICATION_REQUIRED`로 거절하고 프론트가 S-08을 다시 연다. 틀린 횟수 세기와 잠금은 인증 API(`POST /api/auth/pin/verify`)가 맡고, 카드 신청 API는 세지 않는다. 로그인 비밀번호는 묻지 않는다.
2. **신청 자격 (신용카드)**: 만 19세 이상 (`get_age(user) >= 19`). 미달이면 신용카드 선택을 막고 "만 19세 이상부터 신청할 수 있습니다"를 보여준다.
3. **보유 한도**: 해지되지 않은 카드 기준으로 종류별 최대 3장 (분실 카드는 제외). 초과하면 해당 종류 선택을 막고 이유를 보여준다.
4. **신용 한도 부여** (목업 규칙)

| 연소득 구간 | 결과 |
|-------------|------|
| 소득 없음 / 1,000만 원 미만 | **거절** ("소득 확인이 어려워 발급이 어렵습니다") |
| 1,000만 원 ~ 2,000만 원 미만 | 한도 100만 원 |
| 2,000만 원 ~ 4,000만 원 미만 | 한도 300만 원 |
| 4,000만 원 ~ 7,000만 원 미만 | 한도 500만 원 |
| 7,000만 원 이상 | 한도 1,000만 원 |

5. **체크카드**는 심사 없이 바로 발급한다. 1회·1일 한도는 기본값(1회 100만 원, 1일 300만 원)으로 부여한다.
6. **발급 정보 생성**: 카드 번호(끝 4자리만 만든다. 전체 번호·CVC는 이 범위에서 만들지 않는다), 유효기간(발급일 + 5년), 발급일(오늘). 상태는 `active`다. 같은 회원의 모든 카드(해지 포함)와 끝 4자리가 겹치지 않게 한다.
7. **중복 제출 방지**: 신청 버튼을 누르면 결과가 나올 때까지 비활성화한다.
8. 신청 중간에 화면을 벗어나거나 새로고침하면 입력값은 사라져도 된다 (목업).
9. 거절된 신청은 카드로 남지 않는다. 바로 다시 신청할 수 있다.

## 상태별 화면

| 상태 | 처리 |
|------|------|
| 입력 오류 | 해당 항목 아래에 사유 표시. 오류가 있으면 다음 단계로 못 간다 |
| 처리 중 | 신청 버튼 비활성화 + "심사 중..." (체크카드는 "발급 중...") |
| 계좌 목록 불러오기 실패 | 2단계에서 "계좌 정보를 불러오지 못했습니다" + 다시 시도 버튼 |
| 보유 한도·나이 제한 | 1단계에서 해당 종류를 비활성화하고 이유 표시 |

## 데이터

[README의 CardApplication 모델](README.md#4-공통-데이터-모델)과 Card 모델을 쓴다.

- 신청이 성공하면 Card 한 건이 만들어져 카드 목록에 추가된다 (`resultCardId`로 연결).
- 결제 계좌 목록은 일반 계좌 기능(김연준)의 계좌 데이터(`GET /api/accounts?purpose=card_payment`, 본인의 active 저축예금만)에서 가져온다. 계좌 목업이 준비되기 전에는 이 기능의 임시 계좌 목록을 쓴다.
- 목업 단계에서는 결과를 메모리에 두고, 새로고침하면 초기값으로 돌아가도 된다.

## API 명세

공통 규칙은 [00-api-common.md](00-api-common.md), 본인 재확인(간편비밀번호)은 [공통 4절](00-api-common.md#4-본인-재확인-간편비밀번호)을 따른다. 예시는 [목업 기준표](00-api-common.md#10-목업-데이터-기준표) 값이다.

화면이 쓰는 API는 아래 세 개와, 계좌 담당이 제공하는 결제 계좌 목록([공통 7절](00-api-common.md#7-다른-담당에-요구하는-인터페이스))이다.

### `GET /api/card-products` — 신청 가능한 상품

응답 `200`

```json
{
  "items": [
    { "id": "prod_debit_01", "type": "debit", "name": "AIM 체크카드", "description": "결제 계좌에서 바로 출금되는 체크카드" },
    { "id": "prod_credit_01", "type": "credit", "name": "AIM 신용카드", "description": "결제일에 한꺼번에 결제하는 신용카드" }
  ]
}
```

### `GET /api/card-applications/eligibility` — 종류별 신청 가능 여부

1단계에서 불가능한 종류를 미리 막는 데 쓴다.

응답 `200` (user1)

```json
{
  "types": {
    "debit":  { "available": true, "reason": null, "currentCount": 1, "maxCount": 3 },
    "credit": { "available": true, "reason": null, "currentCount": 2, "maxCount": 3 }
  }
}
```

- `currentCount`: 해지·분실 카드를 뺀 보유 장수.
- `reason`: `AGE_UNDER_19`(신용만), `COUNT_EXCEEDED`, 가능하면 `null`. 둘 다 해당하면 `AGE_UNDER_19`를 먼저 돌려준다.
- 이 응답은 안내용이다. 실제 신청(`POST`)에서 서버가 같은 검사를 다시 한다.
- 나이 확인(`get_age(user)`) 호출이 실패하면 `503 MEMBER_SERVICE_UNAVAILABLE`을 돌려준다 (`credit`의 가능 여부를 알 수 없기 때문이다).

### `POST /api/card-applications` — 카드 신청

헤더

| 헤더 | 설명 |
|------|------|
| `Idempotency-Key` | **필수.** UUID v4. 같은 신청을 다시 보낼 때는 같은 값을 쓴다 ([공통 1.7](00-api-common.md#17-중복-요청-방지)) |

요청 본문에는 간편비밀번호를 넣지 않는다. 호출 직전 5분 안에 S-08로 확인한 상태여야 한다 (위 기능 규칙 1).

요청 (신용카드)

```json
{
  "type": "credit",
  "productId": "prod_credit_01",
  "paymentAccountId": 1,
  "paymentDay": 25,
  "incomeRange": "20m_40m",
  "cardPin": "2580",
  "recipient": "홍길동",
  "phone": "010-1234-5678",
  "address": { "line1": "서울시 강남구 테헤란로 1", "line2": "101동 1001호" },
  "agreements": { "cardTerms": true, "privacy": true, "creditInquiry": true }
}
```

요청 (체크카드): `type: "debit"`, `productId: "prod_debit_01"`이고 `paymentDay`, `incomeRange`, `agreements.creditInquiry`는 **보내지 않는다**.

응답 `201` — 승인 (신용카드)

```json
{
  "id": "app_001",
  "type": "credit",
  "status": "approved",
  "requestedAt": "2026-11-04T09:50:00+09:00",
  "grantedLimit": 3000000,
  "rejectReason": null,
  "card": {
    "id": "card_006",
    "name": "AIM 신용카드",
    "type": "credit",
    "numberMasked": "****-****-****-4821",
    "expiry": "11/31",
    "status": "active",
    "issuedAt": "2026-11-04",
    "paymentAccount": { "accountId": 1, "bankName": "AIM Bank", "accountMasked": "****1234" },
    "paymentDay": 25,
    "limit": { "total": 3000000, "used": 0, "remaining": 3000000, "usageRate": 0.0 },
    "debitLimit": null
  },
  "estimatedDeliveryBusinessDays": { "min": 3, "max": 5 }
}
```

응답 `201` — 승인 (체크카드): `grantedLimit: null`, `card.paymentDay: null`, `card.limit: null`, `card.debitLimit: { "perTx": 1000000, "perDay": 3000000 }`

응답 `201` — **거절** (신용카드 소득 조건). 거절은 오류가 아니라 정상 처리 결과라 `201`이다.

```json
{
  "id": "app_002",
  "type": "credit",
  "status": "rejected",
  "requestedAt": "2026-11-04T09:52:00+09:00",
  "grantedLimit": null,
  "rejectReason": "INCOME_INSUFFICIENT",
  "card": null,
  "estimatedDeliveryBusinessDays": null
}
```

### 입력 검증

| 필드 | 규칙 | 위반 시 `reason` |
|------|------|------------------|
| `Idempotency-Key` 헤더 | 필수 | `400 IDEMPOTENCY_KEY_REQUIRED` |
| `type` | 필수, `credit` 또는 `debit` | `REQUIRED`, `INVALID_ENUM` |
| `productId` | 필수, 존재하는 상품이고 `type`과 같은 종류 | `REQUIRED`, `INVALID_ENUM`, `PRODUCT_TYPE_MISMATCH` |
| `paymentAccountId` | 필수 | `REQUIRED` |
| `paymentDay` | 신용만. 정수 1~28. 빼면 25로 처리. 체크에서 보내면 안 됨 | `OUT_OF_RANGE`, `INVALID_FORMAT`, `NOT_ALLOWED` |
| `incomeRange` | 신용 필수. `none`, `lt_10m`, `10m_20m`, `20m_40m`, `40m_70m`, `gte_70m` 중 하나. 체크에서 보내면 안 됨 | `REQUIRED`, `INVALID_ENUM`, `NOT_ALLOWED` |
| `cardPin` | 필수, `^[0-9]{4}$`. 4자리가 모두 같거나(`1111`) 한 칸씩 커지거나 작아지는 숫자(`1234`, `4321`)는 안 됨 (아래 설명 참고) | `REQUIRED`, `INVALID_FORMAT`, `PIN_TOO_SIMPLE` |
| `recipient` | 필수, 앞뒤 공백 제거 후 1~20자 | `REQUIRED`, `TOO_LONG` |
| `phone` | 필수, `^010-[0-9]{4}-[0-9]{4}$` | `REQUIRED`, `INVALID_FORMAT` |
| `address.line1` | 필수, 앞뒤 공백 제거 후 1~100자 | `REQUIRED`, `TOO_LONG` |
| `address.line2` | 선택, 100자 이하 | `TOO_LONG` |
| `agreements.cardTerms`, `agreements.privacy` | 반드시 `true` | `REQUIRED`, `MUST_BE_TRUE` |
| `agreements.creditInquiry` | 신용은 반드시 `true`. 체크에서 보내면 안 됨 | `REQUIRED`, `MUST_BE_TRUE`, `NOT_ALLOWED` |

- **너무 단순한 카드 비밀번호(`PIN_TOO_SIMPLE`)**: 네 자리가 모두 같거나, 앞 숫자보다 항상 `+1`씩(`0123`, `1234`, `6789`) 또는 `-1`씩(`3210`, `4321`, `9876`) 변하는 경우. `7890`처럼 9 다음 0으로 넘어가는 순서는 연속으로 보지 않는다.
- 여러 필드가 틀리면 `details.fields`에 **모두** 담는다.

### 처리 순서

[공통 1.5](00-api-common.md#15-서버-처리-순서)에 신청 전용 검사를 끼운 순서다.

1. 세션 확인 (`current_user`): `401 LOGIN_REQUIRED`/`SESSION_EXPIRED`, 간편비밀번호 미설정이면 `403 PIN_SETUP_REQUIRED`
2. 입력 검증 (`400`): `Idempotency-Key` 헤더(필수, UUID 형식)도 여기서 검증한다
3. 멱등성 확인: 같은 회원이 같은 키로 이미 처리한 신청이면 저장해 둔 응답(`201`)을 그대로 돌려주고 끝. 본문이 다르면 `422 IDEMPOTENCY_KEY_REUSED`
4. 결제 계좌 확인: 내 계좌가 아니거나 저축예금이 아니거나(정기예금·정기적금) 해지된 계좌면 `404 ACCOUNT_NOT_FOUND`
5. 신청 자격: 신용카드이고 만 19세 미만(`get_age(user) < 19`)이면 `422 APPLICANT_NOT_ELIGIBLE` (`reason: "AGE_UNDER_19"`). 나이 확인 호출이 실패하면 `503 MEMBER_SERVICE_UNAVAILABLE`
6. 보유 한도: 같은 종류 보유가 3장 이상이면 `409 CARD_COUNT_LIMIT_EXCEEDED`
7. 본인 재확인 여부 확인 (`pin_verified(request)`): 안 되어 있거나 5분이 지났으면 `403 PIN_VERIFICATION_REQUIRED`
8. 심사·발급 (한 트랜잭션): 신청 기록 저장, 승인이면 카드 생성

- 같은 회원이 같은 종류를 동시에 신청해도 3장을 넘지 않아야 한다. 8단계에서 같은 회원·같은 종류의 신청을 한 번에 하나씩만 처리하고, 그 안에서 장수를 다시 세어 넘으면 `CARD_COUNT_LIMIT_EXCEEDED`로 돌려준다. 구현 방식은 [백엔드 개발 명세](../dev/card/backend-spec.md)에 있다.
- 거절된 신청도 신청 기록(`CardApplication`)은 남긴다. 같은 `Idempotency-Key`로 다시 보내면 거절 응답을 그대로 돌려준다.

### 심사·발급 규칙

**신용 한도 부여**

| `incomeRange` | 결과 |
|---------------|------|
| `none`, `lt_10m` | `rejected`, `rejectReason: "INCOME_INSUFFICIENT"` |
| `10m_20m` | `grantedLimit: 1000000` |
| `20m_40m` | `grantedLimit: 3000000` |
| `40m_70m` | `grantedLimit: 5000000` |
| `gte_70m` | `grantedLimit: 10000000` |

**체크카드**: 심사 없음, 항상 승인. 한도는 1회 1,000,000원 / 1일 3,000,000원.

**발급되는 카드**

| 필드 | 값 |
|------|-----|
| `status` | `active` |
| `issuedAt` | 오늘(KST) |
| `expiry` | 발급일에서 5년 뒤의 `MM/YY` (예: 2026-11-04 발급 → `11/31`) |
| 카드 번호 | 서버가 생성. 끝 4자리는 같은 회원이 가진 모든 카드(해지 포함)와 겹치지 않게 정한다 |
| `paymentDay` | 신용만. 요청 값 (없으면 25) |
| `cardPin` | 형식·단순도만 검증하고 저장하지 않는다. 응답·로그에도 남기지 않는다 |

### 오류

| HTTP | code | 언제 | `details` |
|:----:|------|------|-----------|
| 400 | `VALIDATION_FAILED` | 입력 검증 실패 | `fields` |
| 400 | `IDEMPOTENCY_KEY_REQUIRED` | 키 헤더 없음 | - |
| 401 | `LOGIN_REQUIRED` / `SESSION_EXPIRED` | 로그인하지 않았거나 세션 만료 | - |
| 403 | `PIN_SETUP_REQUIRED` | 간편비밀번호를 아직 설정하지 않음 | - |
| 403 | `PIN_VERIFICATION_REQUIRED` | 5분 안에 간편비밀번호를 확인하지 않음 | - |
| 404 | `ACCOUNT_NOT_FOUND` | 없는 계좌, 남의 계좌, 저축예금이 아니거나 해지된 계좌 | - |
| 409 | `CARD_COUNT_LIMIT_EXCEEDED` | 종류별 3장 초과 | `type`, `current`, `max` |
| 422 | `APPLICANT_NOT_ELIGIBLE` | 신용카드, 만 19세 미만 | `reason: "AGE_UNDER_19"` |
| 422 | `IDEMPOTENCY_KEY_REUSED` | 같은 키에 다른 본문 | - |
| 503 | `ACCOUNT_SERVICE_UNAVAILABLE` | 계좌 서비스 장애 | - |
| 503 | `MEMBER_SERVICE_UNAVAILABLE` | 회원 모듈 호출 실패로 나이 확인 불가 (신용카드) | - |

## 예외·오류 처리

신청 도중에는 화면에서 같은 규칙으로 먼저 검증하고, 서버 오류가 오면 아래처럼 해당 단계로 돌아간다.

| 상황 | API 결과 | 화면 동작 |
|------|----------|-----------|
| 필드 검증 실패 | `400`, `fields` | 필드가 속한 단계로 이동해 해당 입력 아래에 문구 표시. 필드 → 단계: `type`·`productId` → 1단계 / `paymentAccountId`·`paymentDay`·`incomeRange`·`cardPin`·`recipient`·`phone`·`address.*` → 2단계 / `agreements.*` → 3단계 |
| 결제 계좌가 없는 회원 | 계좌 목록이 빔 (계좌 담당 API) | 2단계에서 "결제 계좌로 쓸 수 있는 계좌가 없습니다. 먼저 계좌를 개설해 주세요" 안내, 다음 단계 진행 불가 |
| 선택한 계좌가 그 사이 사라짐·남의 계좌·저축예금이 아닌 계좌 | `404 ACCOUNT_NOT_FOUND` | 2단계로 이동, 계좌 목록을 다시 불러오고 "선택한 계좌를 사용할 수 없습니다" |
| 만 19세 미만 신용카드 | 자격 조회 `AGE_UNDER_19` 또는 `422` | 1단계에서 신용카드 선택 비활성화 + "만 19세 이상부터 신청할 수 있습니다" |
| 종류별 보유 한도(3장) | 자격 조회 `COUNT_EXCEEDED` 또는 `409` | 1단계에서 해당 종류 비활성화 + "{종류} 카드는 최대 3장까지 보유할 수 있습니다" |
| 간편비밀번호 확인 없음·5분 경과 | `403 PIN_VERIFICATION_REQUIRED` | 4단계 유지, S-08을 다시 연다. 통과하면 같은 입력으로 신청을 다시 보낸다 (틀림·잠김 안내는 S-08이 맡는다) |
| 간편비밀번호 미설정 | `403 PIN_SETUP_REQUIRED` | S-07로 이동 |
| 계좌 서비스 장애 | `503` | 4단계 유지, "계좌 정보를 확인할 수 없어 신청하지 못했습니다. 잠시 후 다시 시도해 주세요". 입력값 유지 |
| 응답을 못 받음 (타임아웃·연결 끊김) | 응답 없음 | "신청 결과를 확인하지 못했습니다" + **결과 다시 확인** 버튼. 누르면 **같은 `Idempotency-Key`로** 같은 요청을 다시 보낸다. 서버가 이미 처리했으면 처음 결과를, 아니면 새로 처리한 결과를 돌려준다 |
| 신용카드 심사 거절 | `201`, `status: "rejected"` | 결과 화면에 거절 문구 + "다시 신청하기" (입력값은 비우고 1단계로) |
| 거절 사유 문구 | `INCOME_INSUFFICIENT` | "소득 확인이 어려워 발급이 어렵습니다" |
| 같은 신청이 두 번 제출됨 (더블 클릭·새로고침) | 같은 키 → 같은 응답 | 카드는 한 장만 만들어진다. 버튼은 응답이 올 때까지 비활성화 |
| 새로고침으로 신청 중 이탈 | - | 입력값은 사라진다 (단순화). 1단계부터 다시 시작 |
| 브라우저 뒤로 가기 (신청 단계 중) | - | 이전 단계로 이동한다 (단계를 옮길 때마다 이력 한 칸). 1단계에서 뒤로 가면 카드 목록으로 간다 |
| 결과 화면에서 뒤로 가기 | - | 신청이 끝나면 입력값(`ApplyDraft`)을 비우고 결과 화면(`/cards/apply/result`)은 `replace`로 이동한다. 입력값이 없는 상태로 단계 화면에 들어오면 카드 목록으로 보내므로, 뒤로 가도 신청이 다시 전송되지 않는다 |
| 결과 화면을 새로고침하거나 주소로 직접 엶 | - | 결과 데이터가 없으므로 카드 목록(`/cards`)으로 이동 |
| 1단계의 상품·자격 조회 실패 | `5xx` 또는 네트워크 오류 | 1단계에 "상품 정보를 불러오지 못했습니다" + 다시 시도 버튼, 다음 단계 진행 불가. 조회 중에는 로딩 표시 |
| 체크·신용 모두 선택 불가 | 자격 조회에서 둘 다 `available: false` | 다음 버튼 비활성화 + 각 종류 옆에 이유 문구 |
| 같은 키로 다른 내용을 보냄 | `422 IDEMPOTENCY_KEY_REUSED` | 정상 흐름에서는 일어나지 않는다. 오면 새 키를 만들고 "다시 한 번 신청하기를 눌러 주세요" 안내 (입력값 유지) |
| 회원 서비스 장애 (나이 확인 불가) | `503 MEMBER_SERVICE_UNAVAILABLE` | 4단계 유지, "회원 정보를 확인할 수 없어 신청하지 못했습니다. 잠시 후 다시 시도해 주세요". 입력값 유지 |
| 로그인 만료 | `401` | `/login?next=<원래 경로>`로 이동 (입력값은 사라짐) |

### `Idempotency-Key` 사용 규칙 (프론트)

1. 4단계에서 처음 **신청하기**를 누를 때 UUID v4를 만든다.
2. 응답이 오기 전에 재시도(결과 다시 확인)하면 **같은 키**를 쓴다.
3. 확정된 응답(`201`, 또는 `400`/`403`/`404`/`409`/`422`)을 받으면 키를 버린다. 다음 제출은 새 키를 만든다. (입력을 고쳐서 다시 보내는 것은 다른 요청이다.)
4. `5xx`나 응답 없음일 때만 키를 유지한다.
5. 키를 유지하고 있는 동안 사용자가 입력을 하나라도 고치면 키를 새로 만든다 (같은 키에 다른 본문을 보내면 `422 IDEMPOTENCY_KEY_REUSED`가 되기 때문이다).

## 프론트 구현 메모

- 라우트: `/cards/apply` (단계는 화면 안 상태이며, 단계를 옮길 때마다 브라우저 이력에 한 칸 추가), 결과는 `/cards/apply/result` (`replace` 이동)
- 컴포넌트: `ApplyPage`(단계 컨테이너), `StepIndicator`, `TypeProductStep`, `ApplyFormStep`, `AgreementsStep`, `ConfirmStep`(신청하기 → 필요하면 S-08 간편비밀번호 확인), `ApplyResult`
- 입력값은 상위 상태 하나(`ApplyDraft`)에 두고 단계 이동 때 유지한다. 새로고침하면 사라져도 된다.
- 단계마다 필드 검증은 위 입력 검증 표와 같은 함수 하나로 한다 (서버 규칙과 어긋나지 않게).
- 결제 계좌 목록은 계좌 담당 API(`GET /api/accounts?purpose=card_payment`)에서 2단계에 들어올 때 조회한다.
- 2단계에 들어오면 `GET /api/me`로 수령인(`user.name`)과 연락처(`user.phone`)를 미리 채운다 (수정 가능). 연락처는 하이픈 형식(`010-1234-5678`)으로 보여 주고, 요청에는 위 입력 검증 규칙의 형식으로 보낸다.
- 연소득 구간 표시 문구: `none` 소득 없음 / `lt_10m` 1,000만 원 미만 / `10m_20m` 1,000만~2,000만 원 미만 / `20m_40m` 2,000만~4,000만 원 미만 / `40m_70m` 4,000만~7,000만 원 미만 / `gte_70m` 7,000만 원 이상
- 카드 비밀번호 입력은 가림, 숫자 4자리이고, 확인 입력이 일치해야 다음으로 간다.
- 성공하면 `['cards']` 캐시를 무효화한다.

## 테스트 시나리오

특별한 말이 없으면 user1(로그인한 세션), 결제 계좌 `accountId: 1`, 5분 안에 S-08로 간편비밀번호를 확인한 상태, 오늘 2026-11-04, 유효한 신청 본문(위 예시)을 기준으로 한다. 각 테스트는 기준 데이터에서 시작한다. 단 "직후"·"후"라고 적힌 시나리오(T33, T34 등)는 앞 시나리오가 끝난 상태에서 이어서 한다.

| ID | 구분 | 조건 | 동작 | 기대 결과 |
|----|------|------|------|-----------|
| T01 | API | 체크카드 신청 | `POST` | `201`, `status: "approved"`, `card.status: "active"`, `card.debitLimit` 1000000 / 3000000, `grantedLimit: null`, 만료 `11/31` |
| T02 | API | T01 직후 | `GET /cards` | 새 카드가 목록에 있고 `active` 그룹 맨 앞(발급일 최신) |
| T03 | API | `incomeRange: 10m_20m` | 신용 신청 | `grantedLimit: 1000000` |
| T04 | API | `incomeRange: 20m_40m` | 신용 신청 | `grantedLimit: 3000000`, `card.limit`이 `total: 3000000`, `used: 0`, `remaining: 3000000`, `usageRate: 0.0` |
| T05 | API | `incomeRange: 40m_70m` | 신용 신청 | `grantedLimit: 5000000` |
| T06 | API | `incomeRange: gte_70m` | 신용 신청 | `grantedLimit: 10000000` |
| T07 | API | `incomeRange: lt_10m` | 신용 신청 | `201`, `status: "rejected"`, `rejectReason: "INCOME_INSUFFICIENT"`, `card: null`. 이후 `GET /cards`에 새 카드 없음 |
| T08 | API | `incomeRange: none` | 신용 신청 | T07과 같은 거절 |
| T09 | API | `paymentDay` 생략 (신용) | 신청 | `card.paymentDay: 25` |
| T10 | API | `paymentDay: 28`, `paymentDay: 1` | 신청 | 각각 승인, 값 그대로 |
| T11 | API | `paymentDay: 29`, `0` | 신청 | `400`, `OUT_OF_RANGE` |
| T12 | API | 체크카드에 `paymentDay`, `incomeRange`, `creditInquiry` 포함 | 신청 | `400`, 각 필드 `NOT_ALLOWED` |
| T13 | API | 신용인데 `incomeRange` 없음 | 신청 | `400`, `REQUIRED` |
| T14 | API | `cardPin` `"1111"`, `"1234"`, `"4321"`, `"0123"` | 각각 신청 | 모두 `400`, `PIN_TOO_SIMPLE` |
| T15 | API | `cardPin` `"2580"`, `"7890"`, `"1357"` | 각각 신청 | 모두 승인 |
| T16 | API | `cardPin` `"12345"`, `"12a4"` | 신청 | `400`, `INVALID_FORMAT` |
| T17 | API | `phone: "01012345678"`, `"010-123-5678"` | 신청 | `400`, `INVALID_FORMAT` |
| T18 | API | `recipient`가 21자 / 공백만 | 신청 | 각각 `TOO_LONG` / `REQUIRED` |
| T19 | API | `address.line1` 없음 / 101자 | 신청 | 각각 `REQUIRED` / `TOO_LONG` |
| T20 | API | `agreements.privacy: false` | 신청 | `400`, `MUST_BE_TRUE` |
| T21 | API | 신용인데 `agreements.creditInquiry` 없음 | 신청 | `400`, `REQUIRED` |
| T22 | API | `productId: "prod_debit_01"`에 `type: "credit"` | 신청 | `400`, `PRODUCT_TYPE_MISMATCH` |
| T23 | API | `productId: "prod_x"` | 신청 | `400`, `INVALID_ENUM` |
| T24 | API | 여러 필드가 동시에 틀림 (예: 전화번호 + 약관) | 신청 | `400`, `fields`에 둘 다 포함 |
| T25 | API | S-08 없이 호출 (5분 안의 간편비밀번호 확인 이력 없음) | 신청 | `403 PIN_VERIFICATION_REQUIRED`, 카드 생성 안 됨 |
| T26 | API | 간편비밀번호 확인 후 5분이 지난 뒤 | 신청 | `403 PIN_VERIFICATION_REQUIRED`, 카드 생성 안 됨 |
| T27 | API | 전화번호가 틀리고 S-08도 거치지 않음 | 신청 | `400` (입력 검증이 먼저), `403` 아님 |
| T28 | API | `paymentAccountId: 5` (user2의 계좌), `999` | 신청 | `404 ACCOUNT_NOT_FOUND` |
| T29 | API | user4 (만 18세, 계좌 6) | 신용 신청 | `422`, `reason: "AGE_UNDER_19"` |
| T30 | API | user4 | 체크 신청 | 승인 (나이 제한은 신용만) |
| T31 | API | user4 | `GET /card-applications/eligibility` | `credit.available: false`, `reason: "AGE_UNDER_19"`, `debit.available: true` |
| T32 | API | user1 | `GET /card-applications/eligibility` | `debit` 1/3, `credit` 2/3, 둘 다 `available: true` |
| T33 | API | 신용 신청 승인 후 신용 보유 3장 | 신용 한 번 더 신청 | `409`, `CARD_COUNT_LIMIT_EXCEEDED`, `type: "credit"`, `current: 3`, `max: 3` |
| T34 | API | T33 직후 | `eligibility` | `credit.available: false`, `reason: "COUNT_EXCEEDED"`, `debit`은 가능 |
| T35 | API | 분실 카드(`card_004`)와 해지 카드(`card_005`)는 보유 장수에서 제외 | `eligibility` | 신용 `currentCount: 2`, 체크 `currentCount: 1` |
| T36 | API | 같은 `Idempotency-Key`로 같은 본문 2번 | 신청 | 둘 다 `201`, 같은 `id`, 카드는 한 장만 생성 |
| T37 | API | 거절된 신청을 같은 키로 다시 | 신청 | 같은 거절 응답 (다시 심사하지 않음) |
| T38 | API | 같은 키에 다른 본문 | 신청 | `422 IDEMPOTENCY_KEY_REUSED` |
| T39 | API | 키 헤더 없음 | 신청 | `400 IDEMPOTENCY_KEY_REQUIRED` |
| T40 | API | 신용 보유가 2장일 때 서로 다른 키로 동시에 2건 신청 | 동시에 | 하나만 승인, 다른 하나는 `409 CARD_COUNT_LIMIT_EXCEEDED` (3장 초과 없음) |
| T41 | API | 새 카드 끝 4자리 | 신청 여러 번 | 내 모든 카드(해지 포함)와 겹치지 않음 |
| T42 | API | 계좌 서비스 장애를 흉내 냄 | 신청 | `503`, 카드 생성 안 됨 |
| T43 | API | 로그인하지 않음 (세션 없음) | 신청 | `401 LOGIN_REQUIRED` |
| T44 | API | 거절 직후 | 같은 회원이 새 키로 다시 신청 | 바로 가능 (거절 이력이 신청을 막지 않음) |
| T45 | API | `GET /card-products` | 조회 | 상품 2개 (체크 1, 신용 1) |
| T46 | UI | user1 | 신청 흐름 (체크) 1~4단계 (4단계에서 S-08 통과 후 신청) | 단계 표시 1/5 → 4/5, 이전 단계로 돌아가도 입력 유지, 완료 후 카드 목록에 새 카드 |
| T47 | UI | user3 (계좌 없음, S-07로 간편비밀번호 설정을 마친 뒤) | 2단계 진입 | "먼저 계좌를 개설해 주세요" 안내, 다음 단계 불가 |
| T48 | UI | user4 | 1단계 | 신용카드 선택 비활성화 + 나이 안내 문구 |
| T49 | UI | 신용 신청 | 연소득 `lt_10m` 선택 후 제출 | 거절 결과 화면, "다시 신청하기" 누르면 1단계로 (입력 비움) |
| T50 | UI | 4단계 | 확인 후 5분이 지나 신청하기 (`403 PIN_VERIFICATION_REQUIRED`) | 4단계 유지, S-08이 다시 열림, 통과하면 같은 입력으로 신청 |
| T51 | UI | 4단계 | 제출 직후 응답 전에 연결 끊김 | "결과 다시 확인" 버튼, 누르면 같은 키로 재전송, 카드는 한 장만 |
| T52 | UI | 결과 화면 | 브라우저 뒤로 가기 | 신청이 다시 전송되지 않고 카드 목록으로 이동 |
| T53 | UI | 3단계 | 필수 약관 하나만 해제 | 다음 단계 버튼 비활성화 |
| T54 | UI | 2단계 | 카드 비밀번호와 확인 입력이 다름 | "비밀번호가 일치하지 않습니다", 다음 단계 불가 |
| T55 | API | 회원 서비스 장애를 흉내 냄 | 신용 신청 | `503 MEMBER_SERVICE_UNAVAILABLE`, 카드 생성 안 됨 |
| T56 | API | 같은 키, `cardPin`만 다르게 | 이전 요청이 `201`이었던 경우 신청 | 같은 `201` 응답이 재생됨 (`cardPin`은 본문 비교에서 제외) |
| T57 | API | 첫 요청이 `503`이었음 | 같은 키로 다시 신청 | 새로 처리됨 (오류 응답은 저장되지 않음) |
| T58 | API | `Idempotency-Key: abc` (UUID 아님) | 신청 | `400 VALIDATION_FAILED`, `field: "Idempotency-Key"`, `INVALID_FORMAT` |
| T59 | UI | 4단계 | 응답 없이 끊김 → 입력을 하나 고침 → 다시 제출 | 새 키로 전송 (`422` 없음) |
| T60 | UI | 신청 완료 후 | 결과 화면에서 뒤로 가기 | 카드 목록으로 이동, 신청이 다시 전송되지 않음 |
| T61 | UI | 신청 완료 후 | `/cards/apply/result`를 새로고침 | 카드 목록으로 이동 |
| T62 | UI | 신청 단계 중 | 3단계에서 브라우저 뒤로 가기 | 2단계로 이동 (입력 유지), 1단계에서 뒤로 가면 카드 목록 |
| T63 | UI | 1단계 | 자격 조회 실패 | "상품 정보를 불러오지 못했습니다" + 다시 시도 버튼, 다음 단계 불가 |
| T64 | API | S-08로 간편비밀번호를 확인한 지 5분 안 | 신청 | `201`, 카드 생성 |
| T65 | API | 본인의 정기예금 `paymentAccountId: 3` | 신청 | `404 ACCOUNT_NOT_FOUND`, 카드 생성 안 됨 |

## 완료 기준

- [ ] 카드 목록의 카드 신청 버튼으로 5단계 흐름이 열리고, 이전·다음 이동 시 입력이 유지된다
- [ ] 체크카드를 신청하면 심사 없이 발급되고 목록에 정상 상태로 나타난다
- [ ] 신용카드는 소득 구간별 한도로 발급되고, 1,000만 원 미만은 거절된다
- [ ] 필수 약관 미동의, 형식이 틀린 연락처, 약한 카드 비밀번호가 거절된다
- [ ] 결제 계좌가 없거나 종류별 3장을 넘으면 신청이 막힌다
- [ ] 5분 안에 간편비밀번호를 확인하지 않으면(S-08 없이 호출, 5분 경과) 신청되지 않고 `403 PIN_VERIFICATION_REQUIRED`로 응답한다
