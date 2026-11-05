# 7. 카드 해지

[← 카드 기획서 개요](README.md) · 경로: `/cards/:cardId/terminate` (진입: 내 카드 상세의 **카드 해지** 링크)

## 목적

더 이상 쓰지 않는 카드를 고객이 직접 해지한다. 미결제 금액이 남아 있으면 해지할 수 없게 막는다.

## 용어

| 용어 | 뜻 | 되돌릴 수 있나 |
|------|----|:--------------:|
| 일시정지 | 이용을 잠시 막음 ([04](04-lost-suspend.md)) | O |
| 분실 신고 | 분실·도난으로 카드를 영구 차단 ([04](04-lost-suspend.md)) | X |
| 해지 | 카드 계약을 끝냄. 카드는 다시 쓸 수 없음 | X |

## 사용자 시나리오

- 쓰지 않는 신용카드를 정리한다.
- 해지하려는데 아직 결제하지 않은 금액이 있어서, 얼마가 남았는지 보고 나중에 다시 한다.
- 분실 신고한 카드를 목록에서 정리한다.

## 해지 가능 조건

| 카드 | 조건 |
|------|------|
| 체크카드 | 상태가 정상·일시정지·분실이면 항상 가능 |
| 신용카드 | 상태가 정상·일시정지·분실이고 **이용 금액(미결제)이 0원**일 때 가능 |
| 이미 해지된 카드 | 불가 (해지 링크가 보이지 않음) |

- **이용 금액**은 [공통 계산 기준 6.5](00-api-common.md#65-이용-금액잔여-한도-신용카드)를 따른다: 결제일이 아직 오지 않은(오늘 포함) 청구 주기의 청구액 합계다. 청구는 됐지만 아직 결제일이 되지 않은 금액도 포함한다.
- 목업에는 실제 결제 실행이 없으므로, **결제일이 지난 청구분은 결제 완료로 간주**한다.

## 화면 구성

### 1단계. 해지 가능 확인 (`/cards/:cardId/terminate`)

- 카드 요약: 이름, 종류, 끝 4자리, 결제 계좌
- **해지 가능**이면 2단계 입력을 이어서 보여준다.
- **해지 불가**(미결제 금액이 있는 신용카드)면 해지 입력을 보여주지 않고 다음을 보여준다:
  - "미결제 금액이 있어 해지할 수 없습니다"
  - 미결제 금액, 미결제 청구가 처음 결제되는 날(`firstDueDate`)
  - "미결제 금액을 모두 결제한 뒤 해지할 수 있습니다"
  - 버튼: **청구·결제 예정 금액 보기**(`/cards/billing`), **카드 상세로**

### 2단계. 해지 신청 입력

| 항목 | 규칙 |
|------|------|
| 해지 사유 | 선택 항목(선택 안 해도 됨): 사용하지 않음 / 연회비·혜택 불만 / 다른 카드를 사용 / 분실·도난 후 정리 / 기타 |
| 유의사항 확인 | 필수 체크: "해지하면 되돌릴 수 없고, 이 카드는 다시 쓸 수 없습니다" |
| 본인 재확인 | **해지하기**를 누르면, 5분 안에 확인한 적이 없을 때 S-08(간편비밀번호 확인, 숫자 6자리)이 열린다. 이미 5분 안에 확인했으면 열지 않고 바로 해지를 요청한다 |

- 유의사항 안내 문구:
  - 해지 즉시 카드 이용이 모두 중단된다.
  - 이용내역은 해지 후에도 조회할 수 있다.
  - 카드는 직접 가위로 잘라 폐기해 주세요.
- **해지하기** 버튼은 유의사항 확인을 체크했을 때만 활성화된다.

### 3단계. 완료

- "카드가 해지되었습니다", 카드 이름, 끝 4자리, 해지 일시
- 버튼: **내 카드 목록**(`/cards`)

## 기능 규칙

1. 해지는 되돌릴 수 없다. 해지된 카드를 다시 쓰려면 새로 신청해야 한다 ([06-issuance.md](06-issuance.md)). 해지 직후 같은 상품을 다시 신청해도 된다.
2. 해지하려면 5분 안에 **간편비밀번호(6자리)를 확인(S-08)** 한 상태여야 한다. 확인하지 않았거나 5분이 지났으면 `403 PIN_VERIFICATION_REQUIRED`로 거절하고 S-08을 다시 연다. 틀린 횟수 계산과 잠금은 인증 API가 처리한다 ([공통 4절](00-api-common.md)). 로그인 비밀번호는 묻지 않는다.
3. 처리 즉시 `status`가 `terminated`로 바뀌고, 해지 일시와 선택한 사유를 기록한다.
4. **해지 후 카드의 취급**
   - 내 카드 목록에서는 기본으로 숨기고, 목록 아래 "해지된 카드 보기"로 펼쳐서 볼 수 있다. 해지된 카드에는 "해지" 뱃지가 붙는다.
   - 상세와 이용내역 조회는 가능하다. 일시정지·분실·한도·해지 관련 바로가기는 모두 숨긴다.
   - 청구·결제 예정 화면에는 나오지 않는다 (미결제가 0원이므로).
   - 보유 카드 수 한도 계산([06](06-issuance.md))에는 포함하지 않는다.
5. 분실 카드를 해지해도 분실 신고 기록(`lostAt`, `lostReason`)은 그대로 둔다.
6. 처리 중에는 버튼을 비활성화해 중복 요청을 막는다.
7. 해지 사유는 통계·표시 목적이 아니라 기록용이다. 고객 화면에서 다시 보여주지 않는다.

## 상태별 화면

| 상태 | 처리 |
|------|------|
| 로딩 | 카드 요약·판정 자리에 로딩 표시 |
| 이미 해지된 카드 (`409`) | "해지할 수 없는 카드입니다" + 목록으로 가는 버튼 |
| 존재하지 않는 카드·남의 카드 (`404`) | "카드를 찾을 수 없습니다" + 목록으로 가는 버튼 |
| 해지 불가 (미결제 금액) | 위 1단계의 해지 불가 안내 |
| 본인 재확인 필요 (`403 PIN_VERIFICATION_REQUIRED`) | S-08을 다시 열고, 통과하면 해지 요청을 다시 보냄. 간편비밀번호 미설정(`403 PIN_SETUP_REQUIRED`)이면 S-07로 이동 |
| 처리 중 | 버튼 비활성화 + "처리 중..." |
| 처리 실패(서버 오류) | "해지하지 못했습니다. 잠시 후 다시 시도해 주세요" |

## 데이터

- Card의 `status`를 `terminated`로 바꾸고 `terminatedAt`, `terminatedReason`을 기록한다 ([README Card 모델](README.md#4-공통-데이터-모델)).
- 해지 가능 판정은 [공통 계산 기준 6.5·6.7](00-api-common.md#6-금액-계산-기준-공통)의 이용 금액 계산을 그대로 쓴다. 계산을 따로 만들지 않는다.
- 해지 화면은 두 번 조회한다: 카드 요약·결제 계좌는 카드 상세(`GET /cards/{id}`)에서, 해지 가능 여부는 `termination-check`에서 받는다. 두 조회가 모두 끝나야 화면을 보여주고, 하나라도 실패하면 "다시 시도" 오류 상태를 보여준다.
- 목업 단계에서는 결과를 메모리에 두고, 새로고침하면 초기값으로 돌아가도 된다.

## API 명세

공통 규칙은 [00-api-common.md](00-api-common.md), 해지 가능 계산은 [공통 6.7](00-api-common.md#67-해지-가능-신용카드), 본인 재확인은 [공통 4절](00-api-common.md)을 따른다. 예시는 [목업 기준표](00-api-common.md#10-목업-데이터-기준표) 값이다.

### `GET /api/cards/{cardId}/termination-check` — 해지 가능 여부

1단계 화면에서 해지 입력을 보여줄지, 막을지 정하는 데 쓴다. 안내용이며 실제 해지 때 서버가 다시 확인한다.

응답 `200` — 해지 가능 (`card_003`)

```json
{
  "cardId": "card_003",
  "canTerminate": true,
  "blockReason": null,
  "unpaidAmount": 0,
  "firstDueDate": null
}
```

응답 `200` — 해지 불가 (`card_002`, 오늘 2026-11-04)

```json
{
  "cardId": "card_002",
  "canTerminate": false,
  "blockReason": "UNPAID_BALANCE",
  "unpaidAmount": 1208000,
  "firstDueDate": "2026-11-25"
}
```

- 체크카드는 항상 `canTerminate: true`, `unpaidAmount: 0`.
- 신용카드는 `unpaidAmount`(= 공통 `used`)가 0이면 가능, 0보다 크면 `UNPAID_BALANCE`.
- `firstDueDate`는 불가일 때만 값이 있다. `B(P) > 0`인 주기 중 가장 빠른 결제일, 즉 미결제 청구가 처음 결제되는 날이다. 청구 화면의 `nextPaymentDate`와는 다른 값이다.
- 이미 해지된 카드는 `409 CARD_STATE_INVALID`.

### `POST /api/cards/{cardId}/terminate` — 해지

요청

```json
{ "reason": "unused", "acknowledged": true }
```

| 필드 | 규칙 | 위반 시 `reason` |
|------|------|------------------|
| `reason` | 선택. `unused`(사용하지 않음), `benefit_complaint`(연회비·혜택 불만), `other_card`(다른 카드를 사용), `lost_cleanup`(분실·도난 후 정리), `other`(기타) 중 하나. 없거나 `null`이면 사유 없음 | `INVALID_ENUM` |
| `acknowledged` | 필수, 반드시 `true` (유의사항 확인) | `REQUIRED`, `MUST_BE_TRUE` |

응답 `200`

```json
{
  "id": "card_003",
  "status": "terminated",
  "terminatedAt": "2026-11-04T10:05:30+09:00"
}
```

- 서버에는 `terminatedReason`(받은 사유)을 저장하지만 응답과 상세·목록 조회에는 내보내지 않는다.
- 분실 신고 기록(`lostAt`, `lostReason`)은 해지해도 그대로 둔다.

### 처리 순서

[공통 1.5](00-api-common.md#15-서버-처리-순서)의 순서대로 한다.

1. 로그인 확인(세션) → 2. 입력 검증 → 3. 카드 조회(내 카드가 아니면 `404`) → 4. 상태 확인(이미 해지면 `409 CARD_STATE_INVALID`) → 5. **미결제 금액 확인**(신용, 있으면 `409 CARD_TERMINATE_BLOCKED_UNPAID`) → 6. 본인 재확인 여부 확인(`pin_verified`) → 7. 해지 처리

- 5단계는 `termination-check`를 믿지 않고 **서버가 다시 계산**한다. 확인 화면을 연 뒤 결제 상황이 바뀔 수 있기 때문이다.
- 7단계는 "현재 상태가 해지가 아닐 때만 변경"하는 조건부 갱신이고, 상태 변경과 이력 기록은 한 트랜잭션이다. 이력: 카드, 이전 상태, `terminated`, 일시, 동작 `terminate`.

### 오류

| HTTP | code | 언제 | `details` |
|:----:|------|------|-----------|
| 400 | `VALIDATION_FAILED` | 입력 검증 실패 | `fields` |
| 401 | `LOGIN_REQUIRED` / `SESSION_EXPIRED` | 로그인하지 않음 / 세션 만료 | - |
| 403 | `PIN_SETUP_REQUIRED` | 간편비밀번호를 설정하지 않은 사용자 | - |
| 403 | `PIN_VERIFICATION_REQUIRED` | 5분 안에 간편비밀번호를 확인하지 않음(또는 5분 경과) | - |
| 404 | `CARD_NOT_FOUND` | 없는 카드이거나 남의 카드 | - |
| 409 | `CARD_STATE_INVALID` | 이미 해지된 카드 | `currentStatus: "terminated"`, `allowedStatuses: ["active", "suspended", "lost"]` |
| 409 | `CARD_TERMINATE_BLOCKED_UNPAID` | 미결제 금액이 있는 신용카드 | `unpaidAmount`, `firstDueDate` |

`409` 예시 (미결제)

```json
{
  "code": "CARD_TERMINATE_BLOCKED_UNPAID",
  "message": "미결제 금액이 있어 해지할 수 없습니다.",
  "details": { "unpaidAmount": 1208000, "firstDueDate": "2026-11-25" }
}
```

## 예외·오류 처리

| 상황 | API 결과 | 화면 동작 |
|------|----------|-----------|
| 미결제 금액이 있는 신용카드로 진입 | `termination-check`에서 `canTerminate: false` | 해지 입력 없이 "미결제 금액이 있어 해지할 수 없습니다", 미결제 금액·가장 가까운 결제일, **청구·결제 예정 금액 보기**, **카드 상세로** 버튼 |
| 확인 화면은 통과했는데 제출 시점에 미결제가 생김 | `409 CARD_TERMINATE_BLOCKED_UNPAID` | 위 해지 불가 안내 화면으로 전환 |
| 이미 해지된 카드 (다른 기기에서 먼저 해지, 주소 직접 입력) | `409 CARD_STATE_INVALID` | "해지할 수 없는 카드입니다" + 목록으로 버튼 |
| 없는 카드, 남의 카드 | `404` | "카드를 찾을 수 없습니다" + 목록으로 버튼 |
| 본인 재확인 안 됨·5분 경과 | `403 PIN_VERIFICATION_REQUIRED` | S-08을 다시 열고, 통과하면 해지 요청을 다시 보냄 ([공통 4.4](00-api-common.md)) |
| 간편비밀번호 미설정 | `403 PIN_SETUP_REQUIRED` | S-07로 이동 |
| 요청 후 응답을 못 받음 | 응답 없음 | "해지 결과를 확인하는 중입니다" → 카드 상세를 다시 조회. `terminated`면 완료 화면, 아니면 "해지되지 않았습니다. 다시 시도해 주세요". 자동 재전송 없음 |
| 유의사항 확인을 체크하지 않음 | (요청 안 보냄) | 해지하기 버튼 비활성화 |
| 처리 중 중복 클릭 | - | 요청이 끝날 때까지 버튼 비활성화 |
| 로그인 만료 | `401 LOGIN_REQUIRED` / `SESSION_EXPIRED` | `/login?next=<원래 경로>`로 이동 |
| 체크카드 | 항상 가능 | 판정 API는 똑같이 호출하고(`canTerminate: true`), 판정이 끝나면 곧바로 2단계 입력을 보여준다 |
| 분실 카드 | 미결제 없으면 가능 | 해지 사유에서 `lost_cleanup`을 미리 선택해 두되 바꿀 수 있음 |
| 해지 완료 후 | - | 목록·상세 캐시 무효화. 완료 화면의 **내 카드 목록**으로 이동하면 해당 카드는 기본 목록에서 사라지고 "해지된 카드 보기"에 있음 |
| 해지 완료 화면에서 뒤로 가기 | - | 해지 요청을 다시 보내지 않는다. 완료 화면은 같은 라우트 안의 화면 상태이므로 브라우저 뒤로 가기는 해지 화면 이전 화면(카드 상세)으로 이동하고, 그 화면은 해지된 카드로 새로 조회된다 |

## 프론트 구현 메모

- 라우트: `/cards/:cardId/terminate`. 완료 화면도 같은 라우트 안의 화면 상태이고, **내 카드 목록** 버튼은 일반 이동(`navigate`)이다.
- 컴포넌트: `TerminatePage`, `TerminateBlocked`(해지 불가 안내), `TerminateForm`(사유 선택, 유의사항 체크), `TerminateDone`
- 해지 사유 문구: `unused` 사용하지 않음 / `benefit_complaint` 연회비·혜택 불만 / `other_card` 다른 카드를 사용 / `lost_cleanup` 분실·도난 후 정리 / `other` 기타
- 해지 가능 판정은 화면에 들어올 때 한 번 조회한다. 제출 때 서버가 다시 확인하므로 화면에서는 판정을 다시 부르지 않아도 된다.
- **해지하기**를 누르면 `usePinVerify`(S-08 확인 호출, [frontend-spec 7절](../dev/card/frontend-spec.md#7-간편비밀번호-확인s-08-호출))로 5분 안에 확인했는지 보고, 필요하면 S-08을 연 뒤 해지 API를 부른다. `403 PIN_VERIFICATION_REQUIRED`를 받으면 S-08을 다시 연다.
- 성공하면 `['cards']`, `['card', cardId]` 캐시를 무효화한다.

## 테스트 시나리오

특별한 말이 없으면 user1(id 1), 오늘 2026-11-04, 쓰기 호출은 5분 안에 S-08을 통과한 상태. 각 테스트는 기준 데이터에서 시작한다. 단 "직후"·"이후"라고 적힌 시나리오는 앞 시나리오가 끝난 상태에서 이어서 한다.

| ID | 구분 | 조건 | 동작 | 기대 결과 |
|----|------|------|------|-----------|
| T01 | API | `card_001` (체크, active) | `termination-check` | `canTerminate: true`, `unpaidAmount: 0` |
| T02 | API | `card_003` (신용, suspended, 거래 없음) | `termination-check` | `canTerminate: true`, `blockReason: null` |
| T03 | API | `card_002` (신용, 미결제 있음) | `termination-check` | `canTerminate: false`, `blockReason: "UNPAID_BALANCE"`, `unpaidAmount: 1208000`, `firstDueDate: "2026-11-25"` |
| T04 | API | `card_004` (분실, 미결제 45,000) | `termination-check` | `canTerminate: false`, `unpaidAmount: 45000`, `firstDueDate: "2026-11-25"` |
| T05 | API | `card_005` (해지) | `termination-check` | `409 CARD_STATE_INVALID` |
| T06 | API | `card_003` | `terminate`, `reason: "unused"`, `acknowledged: true` | `200`, `status: "terminated"`, `terminatedAt` 값 있음 |
| T07 | API | T06 직후 | `GET /cards` / `GET /cards?includeTerminated=true` | 기본 목록에 `card_003` 없음, `terminatedCount: 2` / 포함하면 목록 끝쪽의 해지 카드가 `card_003`, `card_005` 순(해지일 최신순) |
| T08 | API | T06 직후 | `GET /cards/card_003` | `status: "terminated"`, `availableActions: ["view_transactions"]`, 응답에 해지 사유 필드 없음 |
| T09 | API | `card_001` (체크) | `terminate`, 사유 없이 | `200` |
| T10 | API | `card_002` (미결제) | `terminate` | `409 CARD_TERMINATE_BLOCKED_UNPAID`, `unpaidAmount: 1208000`, `firstDueDate: "2026-11-25"`, 카드 상태 변화 없음 |
| T11 | API | `card_002`, S-08 통과 없음 | `terminate` | `409` (미결제 오류가 먼저, `403 PIN_VERIFICATION_REQUIRED`가 아님) |
| T12 | API | `card_005` (해지) | `terminate` | `409 CARD_STATE_INVALID` |
| T13 | API | `card_003` | 해지 2번 연속 | 첫 번째 `200`, 두 번째 `409 CARD_STATE_INVALID` |
| T14 | API | `card_003` | `terminate` 동시에 2번 | 하나는 `200`, 다른 하나는 `409` |
| T15 | API | `card_003` | `acknowledged: false` / 없음 | 각각 `400`, `MUST_BE_TRUE` / `REQUIRED` |
| T16 | API | `card_003` | `reason: "xyz"` | `400`, `INVALID_ENUM` |
| T17 | API | `card_003`, S-08 통과 없음 | `terminate` | `403 PIN_VERIFICATION_REQUIRED`, 카드 상태 불변 |
| T18 | API | `card_003`, S-08 통과 후 5분 경과 (시계 이동) | `terminate` | `403 PIN_VERIFICATION_REQUIRED`, 카드 상태 불변 |
| T20 | API | `card_900`, `card_999` | `terminate`, `termination-check` | `404 CARD_NOT_FOUND` |
| T21 | API | 로그인 안 함 / 세션 만료 | `terminate` | `401 LOGIN_REQUIRED` / `401 SESSION_EXPIRED` |
| T23 | API | 시계 2026-11-26 | `card_004` `termination-check` | `canTerminate: true` (11-25 청구가 결제 완료로 지나감) |
| T24 | API | T23 이후 | `card_004` `terminate` | `200`, 이후 상세에 `lostAt`, `lostReason: "lost"` 그대로 있고 `terminatedAt`도 있음 |
| T25 | API | 시계 2027-02-01 | `card_002` `termination-check` | `canTerminate: true` (모든 주기가 결제 완료) |
| T26 | API | `card_003` | `report-lost`(04) 후 `terminate` | 둘 다 `200`. 분실 → 해지 순서가 가능함 |
| T27 | API | 해지 후 | `GET /card-billing/upcoming` | 해지한 카드는 청구에 나타나지 않음 |
| T28 | API | 해지 후 | `GET /card-transactions?cardId=...` | 해지된 카드의 과거 이용내역은 조회됨 |
| T29 | API | 해지 후 | `GET /cards/{id}/limit` | `409 CARD_STATE_INVALID` |
| T30 | API | 분실이 아닌 카드(예: `card_003`)를 해지한 뒤 | `eligibility` | 해당 종류의 `currentCount`가 1 줄어듦(분실 카드는 이미 세지 않으므로 해지해도 변화 없음), 같은 상품을 바로 다시 신청 가능 |
| T31 | UI | `card_003` | 해지 흐름: 사유 선택 → 유의사항 체크 → S-08 간편비밀번호 확인 | 완료 화면(카드 이름·끝 4자리·해지 일시), 목록에서 사라짐 |
| T32 | UI | `card_002` | 해지 화면 진입 | 해지 입력 없음, 미결제 1,208,000원·결제일 2026.11.25 안내, 청구 화면으로 가는 버튼 |
| T33 | UI | `card_003` | 유의사항 미체크 | 해지하기 버튼 비활성화 |
| T34 | UI | `card_003`, 5분 안에 S-08 확인 안 함 | 해지하기 | S-08이 열림. 통과하면 해지 요청이 이어서 전송되어 완료 화면 |
| T35 | UI | 화면 진입 후 다른 곳에서 미결제 발생 | 제출 | `409 CARD_TERMINATE_BLOCKED_UNPAID` → 해지 불가 안내 화면으로 전환 |
| T36 | UI | 해지 완료 | 브라우저 뒤로 가기 | 해지 요청이 다시 전송되지 않고 이전 화면(카드 상세)으로 이동, 그 화면에는 해지된 카드로 이용내역 보기만 있음 |
| T37 | UI | 해지 후 목록 | "해지된 카드 보기" | 해지 뱃지와 함께 펼쳐지고, 상세에는 이용내역 보기만 있음 |
| T38 | UI | 응답 전에 연결 끊김 | 해지 | "결과를 확인하는 중입니다" 후 상세 재조회로 결과 안내, 자동 재전송 없음 |
| T39 | UI | `card_004` (분실), 시계 2026-11-26 | 해지 화면 | 사유 `lost_cleanup`이 미리 선택됨, 바꿀 수 있음 |
| T40 | API | `card_003`, S-08 통과 4분 후 (5분 안) | `terminate` | `200`, `status: "terminated"` |
| T41 | API | user3(id 3, 간편비밀번호 미설정) | `terminate` | `403 PIN_SETUP_REQUIRED` |
| T42 | UI | `card_003`, 5분 안에 S-08 확인함 | 해지하기 | S-08 없이 바로 해지 요청, 완료 화면 |

## 완료 기준

- [ ] 미결제가 없는 신용카드와 체크카드는 해지 입력까지 진행되고, 완료 후 기본 목록에서 사라진다
- [ ] 미결제 금액이 있는 신용카드는 해지 입력이 막히고 금액·결제일 안내가 보인다
- [ ] 유의사항 체크 없이는 해지 버튼이 눌리지 않는다
- [ ] 5분 안에 간편비밀번호를 확인(S-08)하지 않았으면 해지되지 않고 `403 PIN_VERIFICATION_REQUIRED`로 S-08이 다시 열린다
- [ ] "해지된 카드 보기"에서 해지 뱃지가 붙은 카드의 상세·이용내역을 볼 수 있다
- [ ] 해지된 카드에는 정지·분실·한도·해지 바로가기가 보이지 않는다