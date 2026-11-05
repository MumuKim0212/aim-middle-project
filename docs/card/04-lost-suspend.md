# 4. 카드 분실·정지·재개

[← 카드 기획서 개요](README.md) · 경로: `/cards/security` (카드 선택), `/cards/:cardId/security` (상태 화면)

## 목적

카드를 잃어버렸거나 잠시 쓰고 싶지 않을 때, 고객이 직접 이용을 막고 필요하면 다시 풀 수 있게 한다.

## 용어

| 용어 | 뜻 | 되돌릴 수 있나 |
|------|----|:--------------:|
| 일시정지 | 이용을 잠시 막음. 고객이 언제든 해제 | O |
| 정지 해제(재개) | 일시정지를 풀어 다시 이용 가능하게 함 | - |
| 분실 신고 | 분실·도난으로 카드를 영구 차단 | X |

## 사용자 시나리오

- 카드가 안 보이는데 확실하지 않을 때: 일시정지 → 찾으면 해제
- 카드를 잃어버렸거나 도난당했을 때: 분실 신고 → 재발급 안내 확인

## 상태 전이

```
        일시정지            정지 해제
정상 ─────────────▶ 일시정지 ─────────────▶ 정상
 │                     │
 └──── 분실 신고 ──────┴──────────────▶ 분실 (이 화면에서는 더 할 수 없음. 해지만 07에서 가능)
```

| 현재 상태 | 가능한 동작 |
|-----------|-------------|
| 정상 | 일시정지, 분실 신고 |
| 일시정지 | 정지 해제, 분실 신고 |
| 분실 | 없음 (재발급 안내만 표시. 카드 해지는 [07-termination.md](07-termination.md)에서) |
| 해지 | 없음 (이 화면에 들어오면 카드 상세로 보낸다) |

## 화면 구성

### 카드 선택 (`/cards/security`)

- 카드 상세에서 들어오면 이 선택 화면을 거치지 않고 곧바로 그 카드의 상태 화면(`/cards/:cardId/security`)이 열린다.
- 메뉴의 **분실·정지·재개**로 들어오면 `/cards/security`에서 카드 선택 목록을 먼저 보여준다. 카드를 고르면 `/cards/:cardId/security`로 이동한다.
- 목록은 해지되지 않은 카드(`GET /cards`)다. 항목에는 카드 이름, 종류 뱃지, 끝 4자리, 상태 뱃지를 보여준다. 분실 카드도 고를 수 있고, 고르면 상태 화면에 분실 안내만 나온다.
- 목록에 카드가 없으면(카드가 없거나 해지된 카드뿐) "처리할 수 있는 카드가 없습니다" 안내와 **카드 신청** 버튼을 보여준다.

### 상태 화면 (`/cards/:cardId/security`)

| 카드 상태 | 보여주는 것 |
|-----------|-------------|
| 정상 | 상태 "정상 이용 가능", 버튼 **일시정지**, **분실 신고** |
| 일시정지 | 상태 "일시정지 중", 정지한 일시, 버튼 **정지 해제**, **분실 신고** |
| 분실 | 상태 "분실 신고됨", 신고 일시, 사유(분실 / 도난), 재발급 안내 문구 (버튼 없음) |
| 해지 | 이 화면을 보여주지 않고 카드 상세(`/cards/:cardId`)로 이동 (`replace`) |

### 일시정지

1. 일시정지 버튼 → 확인 팝업 ("이 카드의 모든 이용이 중단됩니다. 계속할까요?")
2. 간편비밀번호 확인(S-08). 5분 안에 이미 확인했으면 건너뛴다
3. 완료 → 상태 화면이 "일시정지 중"으로 바뀐다

### 정지 해제

1. 정지 해제 버튼 → 확인 팝업
2. 간편비밀번호 확인(S-08). 5분 안에 이미 확인했으면 건너뛴다
3. 완료 → 상태 화면이 "정상"으로 바뀐다

### 분실 신고

1. 분실 신고 버튼 → 사유 선택: **분실** / **도난**
2. 경고 팝업: "신고하면 되돌릴 수 없고 이 카드는 다시 쓸 수 없습니다."
3. 간편비밀번호 확인(S-08). 5분 안에 이미 확인했으면 건너뛴다
4. 완료 → 상태 "분실 신고됨", 재발급 안내 문구 표시

## 기능 규칙

1. 일시정지·정지 해제·분실 신고는 모두 **최근 5분 안에 간편비밀번호(6자리)를 확인한 사용자**만 처리한다(`pin_verified`). 로그인 비밀번호는 묻지 않는다.
2. 확인하지 않았거나 5분이 지났으면 `403 PIN_VERIFICATION_REQUIRED`로 처리하지 않고, 프론트가 S-08을 다시 연다. 틀린 횟수 계산과 5회 잠금(`423 PIN_LOCKED`)은 인증 API(`/api/auth/pin/verify`)에서 처리하며, 카드 API는 횟수를 세지 않는다.
3. 처리 결과는 즉시 반영된다. 반영 후 카드 목록·상세의 상태 뱃지도 바뀌어야 한다.
4. 분실 신고 후에도 이미 발생한 이용내역·청구는 계속 조회되고 청구된다.
5. 분실 신고 사유(분실 / 도난)는 기록하고, 신고 일시와 함께 분실 상태 화면과 카드 상세의 분실 안내에 다시 보여준다.
6. 재발급은 이번 범위 밖이다. 분실 후에는 "고객센터로 재발급을 신청해 주세요" 문구만 보여준다.
7. 처리 중에는 버튼을 비활성화해 중복 요청을 막는다.

## 상태별 화면

| 상태 | 처리 |
|------|------|
| 처리 중 | 버튼 비활성화 + "처리 중..." |
| 처리 성공 | 완료 문구 ("일시정지 되었습니다" 등)와 갱신된 상태 화면 |
| 본인 재확인 필요 (`403 PIN_VERIFICATION_REQUIRED`) | S-08을 다시 연다. 카드 상태는 그대로 |
| 처리 실패(서버 오류) | "처리하지 못했습니다. 잠시 후 다시 시도해 주세요" |

## 데이터

- Card의 `status`를 변경한다. 추가로 `suspendedAt`, `lostAt`, `lostReason`(`lost` | `stolen`)을 둔다.
- 목업 단계에서는 변경값을 메모리(상태 관리)에 두어 화면 간 일관되게 보여준다. 새로고침하면 초기값으로 돌아가는 것은 허용한다.
- 본인 재확인은 인증 기능의 `pin_verified(request)`와 S-08을 쓴다 ([공통.md 4장](../common/공통.md)). 카드 화면은 간편비밀번호를 입력받거나 보관하지 않는다.
- 간편비밀번호는 카드 화면·요청·로그에 남기지 않는다.

## API 명세

공통 규칙은 [00-api-common.md](00-api-common.md), 본인 재확인(간편비밀번호)은 [공통 4절](00-api-common.md)과 [공통.md 4장](../common/공통.md), 상태 전이는 [공통 5절](00-api-common.md#5-카드-상태-전이-서버-기준)을 따른다. 예시는 [목업 기준표](00-api-common.md#10-목업-데이터-기준표) 값이다.

세 API는 모두 요청 본문에 간편비밀번호를 받지 않는다. 호출 직전 5분 안에 S-08(`POST /api/auth/pin/verify`)로 확인해 세션에 `pin_verified_at`이 기록되어 있어야 하고, 같은 모양의 결과를 돌려준다.

**공통 결과 (`CardStatusResult`)**

```json
{
  "id": "card_002",
  "status": "suspended",
  "suspendedAt": "2026-11-04T09:45:12+09:00",
  "lostAt": null,
  "lostReason": null
}
```

- `suspendedAt`은 상태가 `suspended`인 동안에만 값이 있다. 해제하거나 분실 신고하면 `null`이 된다.

### `POST /api/cards/{cardId}/suspend` — 일시정지

요청: 본문 없음

- 허용 상태: `active` → 결과 상태 `suspended`
- 응답 `200`: `status: "suspended"`, `suspendedAt` 값 있음

### `POST /api/cards/{cardId}/resume` — 정지 해제

요청: 본문 없음

- 허용 상태: `suspended` → 결과 상태 `active`
- 응답 `200`: `status: "active"`, `suspendedAt: null`

### `POST /api/cards/{cardId}/report-lost` — 분실 신고

요청

```json
{ "reason": "stolen" }
```

- 허용 상태: `active`, `suspended` → 결과 상태 `lost` (되돌릴 수 없음)
- 응답 `200`: `status: "lost"`, `lostAt` 값 있음, `lostReason: "stolen"`, `suspendedAt: null`

### 입력 검증

| 필드 | 규칙 | 위반 시 `reason` |
|------|------|------------------|
| `reason` (분실 신고만) | 필수, `lost`(분실) 또는 `stolen`(도난) | `REQUIRED`, `INVALID_ENUM` |

### 처리 순서

[공통 1.5](00-api-common.md#15-서버-처리-순서)의 순서대로 한다.

1. 세션 확인 → 2. 입력 검증 → 3. 카드 조회(내 카드가 아니면 `404`) → 4. 상태 확인(허용 상태가 아니면 `409`) → 5. 본인 재확인 여부 확인(`pin_verified`, 안 되어 있거나 5분이 지났으면 `403 PIN_VERIFICATION_REQUIRED`) → 6. 상태 변경

- 6단계: "현재 상태가 허용 상태일 때만 변경"하는 조건부 갱신으로 처리하고, 갱신된 행이 없으면 `409 CARD_STATE_INVALID`를 돌려준다 (동시 요청 방어).
- 상태 변경과 상태 이력 기록은 한 트랜잭션이다. 이력: 카드, 이전 상태, 새 상태, 일시, 동작(`suspend` / `resume` / `report_lost`).

### 오류

| HTTP | code | 언제 | `details` |
|:----:|------|------|-----------|
| 400 | `VALIDATION_FAILED` | 위 입력 검증 실패 | `fields` |
| 401 | `LOGIN_REQUIRED` / `SESSION_EXPIRED` | 로그인 안 함 / 세션 만료 | - |
| 403 | `PIN_SETUP_REQUIRED` | 간편비밀번호를 아직 설정하지 않음 | - |
| 403 | `PIN_VERIFICATION_REQUIRED` | 본인 재확인(S-08)을 안 했거나 5분이 지남 | - |
| 404 | `CARD_NOT_FOUND` | 없는 카드이거나 남의 카드 | - |
| 409 | `CARD_STATE_INVALID` | 허용 상태가 아님 (이미 정지·분실·해지 등) | `currentStatus`, `allowedStatuses` |

`409` 예시

```json
{
  "code": "CARD_STATE_INVALID",
  "message": "현재 카드 상태에서는 처리할 수 없습니다.",
  "details": { "currentStatus": "suspended", "allowedStatuses": ["active"] }
}
```

## 예외·오류 처리

| 상황 | API 결과 | 화면 동작 |
|------|----------|-----------|
| 본인 재확인 안 됨·5분 경과 | `403 PIN_VERIFICATION_REQUIRED` | S-08을 다시 연다. 카드 상태는 그대로. 간편비밀번호 불일치·잠금 안내는 S-08이 맡는다 |
| 간편비밀번호 미설정 | `403 PIN_SETUP_REQUIRED` | S-07로 이동 |
| 그 사이 카드 상태가 바뀜 (다른 기기·중복 탭) | `409 CARD_STATE_INVALID` | 팝업을 닫고 카드를 다시 조회해 새 상태 화면 표시 + "카드 상태가 이미 바뀌었습니다" 안내 |
| 요청 후 응답을 못 받음 (타임아웃·연결 끊김) | 응답 없음 | "처리 결과를 확인하는 중입니다" → 카드 상세를 다시 조회해 상태가 기대한 값이면 성공 처리, 아니면 "처리되지 않았습니다. 다시 시도해 주세요". 이 경우 같은 요청을 자동으로 다시 보내지 않는다 |
| 카드가 내 것이 아니거나 없음 | `404` | 카드 목록으로 이동 + "카드를 찾을 수 없습니다" |
| 로그인 안 함·세션 만료 | `401 LOGIN_REQUIRED` / `SESSION_EXPIRED` | `/login?next=<원래 경로>`로 이동 |
| 분실 신고 사유를 고르지 않음 | (요청 안 보냄) | 다음 버튼 비활성화 |
| 분실 카드의 상태 화면 진입 | 상세의 `availableActions`에 정지·분실 동작 없음 | 버튼 없이 분실 안내만 (신고 일시·사유·재발급 안내) |
| 해지된 카드의 상태 화면 진입 (주소 직접 입력 등) | 상세의 `status: "terminated"` | 카드 상세로 이동 (`replace`) |
| 처리 중 중복 클릭 | - | 요청이 끝날 때까지 확인 버튼 비활성화 |

## 프론트 구현 메모

- 라우트: `/cards/security` (카드 선택), `/cards/:cardId/security` (상태 화면)
- 컴포넌트: `CardPickerPage`(한도 조회와 공용, 선택 가능한 카드 조건을 props로 받음), `SecurityPage`, `CardStatusPanel`, `SuspendFlow`, `ResumeFlow`, `ReportLostFlow`(사유 선택 → 경고 → 간편비밀번호 확인)
- 본인 재확인은 공용 S-08(간편비밀번호 확인, 인증 담당)을 띄워 처리한다 ([공통 4.4](00-api-common.md)). 입력은 6자리(`inputMode="numeric"`, `maxLength=6`)이고 S-08 소관이다. 5분 안에 이미 확인했으면(`verifiedUntil` 기준) S-08을 띄우지 않는다.
- 쓰기 API가 `403 PIN_VERIFICATION_REQUIRED`를 돌려주면 S-08을 다시 열고, `403 PIN_SETUP_REQUIRED`면 S-07로 보낸다.
- 버튼은 상세 응답의 `availableActions`로 정한다 (`suspend`, `resume`, `report_lost`).
- 성공하면 `['cards']`, `['card', cardId]` 캐시를 무효화하고 응답의 `status`로 화면을 바로 갱신한다.
- 완료 문구: "일시정지 되었습니다", "정지가 해제되었습니다", "분실 신고가 접수되었습니다".

## 테스트 시나리오

특별한 말이 없으면 user1(id 1), 오늘 2026-11-04, 쓰기 API는 호출 직전 5분 안에 S-08로 간편비밀번호를 확인한 상태(`pin_verified`), 각 테스트는 기준 데이터에서 시작한다. 단 "직후"라고 적힌 시나리오는 바로 앞에서 말한 시나리오가 끝난 상태에서 이어서 한다.

| ID | 구분 | 조건 | 동작 | 기대 결과 |
|----|------|------|------|-----------|
| T01 | API | `card_002` (active) | `suspend` | `200`, `status: "suspended"`, `suspendedAt` 값 있음 |
| T02 | API | T01 직후 | 같은 카드 `suspend` 다시 | `409`, `currentStatus: "suspended"`, `allowedStatuses: ["active"]` |
| T03 | API | `card_003` (suspended) | `resume` | `200`, `status: "active"`, `suspendedAt: null` |
| T04 | API | `card_002` (active) | `resume` | `409`, `allowedStatuses: ["suspended"]` |
| T05 | API | `card_002` (active) | `report-lost`, `reason: "stolen"` | `200`, `status: "lost"`, `lostAt` 값 있음, `lostReason: "stolen"` |
| T06 | API | `card_003` (suspended) | `report-lost`, `reason: "lost"` | `200`, `status: "lost"`, `suspendedAt: null` |
| T07 | API | `card_004` (lost) | `report-lost` | `409`, `currentStatus: "lost"`, `allowedStatuses: ["active", "suspended"]` |
| T08 | API | `card_005` (terminated) | `suspend`, `resume`, `report-lost` 각각 | 모두 `409`, `currentStatus: "terminated"` |
| T09 | API | `card_002` (active), 간편비밀번호 확인 이력 없음 (S-08을 거치지 않음) | `suspend` | `403 PIN_VERIFICATION_REQUIRED`, 카드 상태 변화 없음 |
| T10 | API | `card_002` (active), 확인 후 시계를 5분 이상 뒤로 | `suspend` | `403 PIN_VERIFICATION_REQUIRED`, 카드 상태 변화 없음 |
| T11 | API | T10 직후 | S-08로 다시 확인한 뒤 `suspend` | `200`, `status: "suspended"` |
| T12 | API | `card_002` (active), 확인 후 시계를 4분 뒤로 | `suspend` | `200` (5분 안이므로 통과) |
| T13 | API | `card_001`, `card_003` (둘 다 결제 계좌 1) | 한 번 확인한 뒤 `card_001` suspend(`200`) → 5분 안에 다시 확인하지 않고 `card_003` resume | 두 번째도 `200` (본인 재확인은 요청마다가 아니라 5분 동안 유효) |
| T16 | API | `card_002` | `report-lost`에서 `reason` 없음 / `"missing"` | `400`, 각각 `REQUIRED` / `INVALID_ENUM` |
| T17 | API | `card_002` (active), 확인 이력 없음 | `resume` | `409` (상태 오류가 먼저, `403`보다 앞) |
| T18 | API | `card_003` (suspended), 확인 이력 없음 | `report-lost`, `reason: "missing"` | `400 INVALID_ENUM` (입력 검증이 먼저) |
| T19 | API | user1 | `card_900`, `card_999`에 `suspend` | 모두 `404 CARD_NOT_FOUND` |
| T20 | API | 로그인 안 함 / 세션 만료 | `suspend` | `401 LOGIN_REQUIRED` / `401 SESSION_EXPIRED` |
| T21 | API | `card_001`(결제 계좌 1), `card_002`(결제 계좌 2) | 한 번 확인한 뒤 5분 안에 `card_001` suspend → `card_002` suspend | 둘 다 `200` (재확인은 계좌가 아닌 사용자 단위) |
| T22 | API | `card_002` | `suspend`를 동시에 2번 | 하나는 `200`, 다른 하나는 `409` |
| T24 | API | T01 직후 | `GET /cards/card_002`, `GET /cards` | 상세 `status: "suspended"`, `availableActions`는 `view_transactions`, `view_limit`, `resume`, `report_lost`, `terminate`. 목록 순서 `card_001`, `card_003`, `card_002`, `card_004` |
| T25 | API | T05 직후 | `GET /card-billing/upcoming` | 분실 신고한 `card_002`의 900,000원이 그대로 청구에 포함 |
| T26 | API | T01 직후 | 서버 상태 이력 | (`card_002`, `active` → `suspended`, `suspend`) 한 건 기록 |
| T27 | UI | `card_002` 상태 화면 | 일시정지 → 확인 → S-08에서 간편비밀번호 확인 | 완료 문구, 상태 "일시정지 중", 정지한 일시 표시, 버튼이 정지 해제·분실 신고로 바뀜 |
| T28 | UI | 확인한 지 5분이 지난 상태 | 일시정지 → 확인 | API `403 PIN_VERIFICATION_REQUIRED` → S-08이 다시 열림, 카드 상태 그대로 |
| T29 | UI | user3 (간편비밀번호 미설정) | 일시정지 → 확인 | API `403 PIN_SETUP_REQUIRED` → S-07로 이동 |
| T30 | UI | 분실 신고 | 사유를 고르지 않음 | 다음 버튼 비활성화. 사유 선택 → 경고 팝업 → S-08 순서로 진행 |
| T31 | UI | `card_004` (분실) 상태 화면 | 진입 | 버튼 없음, "분실 신고됨"·신고 일시·사유 "분실"·재발급 안내 문구 |
| T32 | UI | 다른 기기에서 먼저 정지됨 | 정상 화면에서 일시정지 시도 | `409` → 팝업 닫힘, 상태 화면이 "일시정지 중"으로 갱신, 안내 문구 |
| T33 | UI | 응답 전에 연결 끊김 | 일시정지 | "처리 결과를 확인하는 중입니다" 후 상태 재조회로 결과 안내, 자동 재전송 없음 |
| T34 | UI | 일시정지·정지 해제·분실 신고 | 요청 확인 | 카드 화면에 간편비밀번호 입력창이 없고(S-08이 처리), 요청 본문에도 간편비밀번호가 없음 |
| T35 | UI | `card_005` (해지) | `/cards/card_005/security`로 직접 접근 | 카드 상세로 이동 |
| T36 | UI | user1 | 메뉴의 분실·정지·재개 → `/cards/security` | 카드 선택 목록에 `card_001`~`card_004`(해지 `card_005` 제외), 분실 카드를 고르면 분실 안내만 있는 상태 화면 |
| T37 | UI | user3 (S-07 완료 후, 카드 없음) | `/cards/security` | "처리할 수 있는 카드가 없습니다" + 카드 신청 버튼 |
| T38 | API | `card_003` (suspended), 확인 이력 없음 | `resume`, 이어서 `report-lost` | 모두 `403 PIN_VERIFICATION_REQUIRED`, 카드 상태 변화 없음 |
| T39 | API | user3 (간편비밀번호 미설정) | `suspend` | `403 PIN_SETUP_REQUIRED` |
| T40 | UI | S-08을 방금 통과함 | 5분 안에 정지 해제 같은 두 번째 동작 | S-08을 띄우지 않고 바로 처리 |

## 완료 기준

- [ ] 정상 카드가 일시정지되고, 다시 해제된다
- [ ] 분실 신고 후에는 어떤 버튼도 남지 않고 재발급 안내만 보인다
- [ ] 간편비밀번호 확인(S-08) 없이, 또는 5분이 지난 뒤 호출하면 처리되지 않고 `403 PIN_VERIFICATION_REQUIRED`다
- [ ] 정지·해제·분실 신고에서 로그인 비밀번호를 묻지 않는다
- [ ] 상태 변경이 카드 목록·상세의 뱃지에 반영된다
- [ ] 분실 카드의 이용내역은 계속 조회된다
