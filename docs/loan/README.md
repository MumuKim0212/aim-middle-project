# 대출 문서

| 항목 | 내용 |
|---|---|
| 담당 | 임대진 |
| 상태 | 서버 통합 완료(`backend/app/loan/`, 2026-11-06). 화면(React, `/loans`: 관리, `/loans/apply/...`: 신청)은 구현. 자연어는 별도 기능으로 분리 |
| 공통 규칙 | [공통.md](../common/공통.md). 이 폴더의 문서가 공통.md와 다르면 이 폴더를 고친다 |

## 문서

| 문서 | 내용 |
|---|---|
| [Loan_Service_main.md](Loan_Service_main.md) | 대출 서비스 전체 기획(흐름·동의·심사·추천·LLM 게이트웨이·DB) |
| [Loan_Service/](Loan_Service/) | 일반대출·정부대출·기관대출 기획서, 서식 PDF(LN-01~28) |
| [Refinancing_Service/](Refinancing_Service/) | 대환대출 기획서, 서식 PDF(RF-01~19) |
| [대출관리_기획서.md](대출관리_기획서.md) | 계좌 조회·스케줄·중도상환·금리인하·철회·연장·증명서 |
| [Prototype/](Prototype/), [Design/](Design/) | 프로토타입 HTML과 구현명세, 화면 디자인 시안·가이드 |
| [Customer_Submission_Documents/](Customer_Submission_Documents/README.md) | 체험 고객 제출서류 샘플(정답표 포함) |
| [대출서비스_종합정리.md](대출서비스_종합정리.md) | 서버 구현 정리: 실행법, DB 설계, 가드레일, 테스트, 한계 |
| [erd/](erd/) | ERD 8장과 생성 스크립트 |

기획서(`Loan_Service_main.md` 등)는 원안이라 API 경로(`/loans/...`), 오류 형식(`reason_codes[]`), 멱등 범위가 구현과 다를 수 있다. 어긋나면 이 문서와 [오류코드.md 5.1](../common/오류코드.md)이 기준이다.

## API (`/api/loans`)

모든 API는 로그인 필요(상품 목록 제외). 오류는 [오류코드.md 5.1](../common/오류코드.md). 실행·중도상환·청약철회는 간편비밀번호 재확인(`PIN_VERIFICATION_REQUIRED`)이 필요하고, 실행·중도상환은 `Idempotency-Key` 헤더(8~36자)도 받는다.

| 메서드 · 경로 | 내용 |
|---|---|
| `GET /products` | 상품 목록(로그인 없이) |
| `GET /` | 내 대출 목록 |
| `GET /{no}` · `/{no}/schedule` · `/{no}/prepay-quote?principal=` | 대출 상세(연체 중이면 `overdue: { startDate, days, stage, installment, penalty, total }`, 아니면 `null`), 남은 상환 일정, 중도상환 견적(`penalty` 포함) |
| `POST /{no}/prepay` `{ principal, accountId? }` | 중도상환. 내 저축예금에서 총액 출금 (`accountId` 없으면 자동이체 계좌). 연체 중에도 가능하고 전액 상환이면 지연배상금(`penalty`)이 더해진다 |
| `PUT /{no}/auto-debit` `{ accountId }` | 월 상환 자동이체 계좌 변경(간편비밀번호 재확인, 내 활성 저축예금만). ACTIVE·OVERDUE 대출 |
| `POST /{no}/withdraw` | 청약철회(실행 후 14일 이내). 받은 계좌에서 원금·이자를 되돌려 받음 |
| `POST /{no}/rate-cut` `{ reasons }`, `/{no}/extend` `{ months }`, `/{no}/certificates` `{ type }` | 금리인하요구, 기간연장, 증명서 |
| `POST /applications` `{ productId, scenarioKey? }` | 신청 시작. 응답 `applicationId`, `flow`(단계 목록) |
| `GET /applications/{id}` | 진행 상태 |
| `POST /applications/{id}/precheck` | (정부) 자격 사전 확인 |
| `GET·POST /applications/{id}/consents` | 필수 동의 목록, 동의 제출 |
| `POST /applications/{id}/existing` · `/targets` | (대환) 기존 대출 조회, 대환 대상 선택 |
| `POST /applications/{id}/profile` | 고객정보·적합성 판정 |
| `POST /applications/{id}/policy-check` · `GET .../guarantee-options` · `POST .../guarantee` · `POST .../affiliation` | (정부) 정책 자격, (기관) 보증기관 선택·협약기관 재직 확인 |
| `GET·POST /applications/{id}/docs` | 필요 서류, 증빙 제출(`autoLink`) |
| `POST /applications/{id}/docs/upload` (multipart `docKey`, `file`) | 증빙 파일 업로드(pdf·png·jpg, 10MB, 신청당 20개). 응답 `defects` |
| `POST /applications/{id}/review` | 심사 |
| `GET /applications/{id}/recommendations` · `POST .../choose` · `POST .../compare` | 권장 상품 3안, 선택, (대환) 유불리 비교 |
| `POST /applications/{id}/terms` `{ amount, term, repay, paymentDay, debitAccountId }` | 조건 확정. `debitAccountId`는 내 저축예금 |
| `POST /applications/{id}/price` | 금리 산정(우대). 응답에 적용된 우대 `appliedPrefs`, 못 받은 우대 `deniedPrefs`(카드 사용 우대는 직전 달 승인액 순합계 30만원 이상일 때만) |
| `GET /applications/{id}/quiz` · `POST .../explain` | 이해 확인 문제(정답은 내려주지 않음), 설명의무 확인 |
| `POST /applications/{id}/contract` · `/collateral` | 약정(전자서명 자리), 담보·보증 설정 |
| `POST /applications/{id}/execute` `{ accountId }` | 실행. 본인 지급(신용·예금담보) 대출금을 `accountId` 내 저축예금에 입금 |

신청 진행 상태는 서버 메모리에 30분 보관하고 DB(`loan_application.session_state`)에도 저장해, 재시작 뒤에도 내 진행 중 신청을 복원한다(추천 후보 포함). 매일 00:20 KST에 월 상환 자동이체 배치가 돈다. 자세한 한계는 [대출서비스_종합정리.md 8장](대출서비스_종합정리.md).
