# 문서 목차

기획·설계 문서의 위치와 읽는 순서다. 문서끼리 내용이 다르면 [공통 기획서](common/공통.md)가 기준이다.

## 읽는 순서

1. [공통 기획서](common/공통.md): 여러 파트가 함께 지키는 규칙 (인증, 본인 재확인, 오류 코드, 데이터 규칙, 공통 시드, 파트 사이 인터페이스, 자연어 구조)
2. [기술 스택](common/기술스택.md): 기술 선택, 버전, 폴더 구조, 개발 환경 세팅
3. [오류 코드](common/오류코드.md): 프론트와 백엔드가 같이 쓰는 `code` 목록
4. 맡은 파트의 기획서 (아래 표)

## 문서 위치

| 폴더 | 문서 | 내용 | 담당 |
|---|---|---|---|
| `common/` | [공통.md](common/공통.md) | 공통 규칙, 결정 기록, 파트 문서 반영 현황 | `main` 브랜치가 기준본 (작성 김경민) |
| `common/` | [오류코드.md](common/오류코드.md) | 오류 코드 목록(공통·인증·계좌 원본, 카드 색인), 필드 오류 사유 | 공통.md와 같음 |
| `common/` | [기술스택.md](common/기술스택.md) | 스택, 환경, 폴더 구조 | 팀 |
| `auth/` | [회원,인증.md](auth/회원,인증.md) | 회원가입, 로그인·로그아웃, 간편비밀번호, 2차 인증, 접근 제어. 실패 시나리오 확인 결과는 `auth/auth-check.md` | 김연준 |
| `account/` | [계좌.md](account/계좌.md) | 저축예금·정기예금·정기적금, 개설·이체·해지, 이자 계산 | 김연준 |
| `card/` | [README.md](card/README.md) | 카드 기획서 개요, 기능별 상세 `00`~`08` | 김경민 |
| `dev/card/` | [backend-spec.md](dev/card/backend-spec.md), [frontend-spec.md](dev/card/frontend-spec.md) | 카드 개발 명세 (DB, 서버 규칙, 프론트 구조) | 김경민 |
| `db/` | [db-design.md](db/db-design.md), [erd.md](db/erd.md) | 통합 DB 설계, ERD | |
| `Proposal/`, `loan_service/` | [Loan_Service_main.md](../Proposal/Loan_Service_main.md), [대출서비스_종합정리.md](../loan_service/대출서비스_종합정리.md) | 대출 기획서 원문(일반·정부·기관·대환·대출관리), 대출 서비스 구현(DB 스키마, CLI)과 요약 | 임대진 |
| `references/` | 화면 캡처 | 우리WON뱅킹 참고 화면 (`card/`, `account/`, `loan/`) | |
| `screenshots/` | 구현 화면 캡처 | | |

## 폴더 규칙

- 파트(auth, account, card, …)마다 폴더를 하나 두고, 기획서는 그 안에 둔다.
- 개발 명세(DB, 서버 구현 규칙, 프론트 구조)는 기획서와 분리해 `dev/<파트>/`에 둔다.
- 파트 문서는 공통 규칙을 복사하지 않고 `common/공통.md`로 링크한다 (공통.md 0장).
- `common/` 아래 문서는 누구나 고칠 수 있지만 **`main` 브랜치에서만** 고친다. 파트 브랜치(feature/*)에서는 고치지 않는다.
- 새 오류 코드는 `common/오류코드.md`에 먼저 추가한다.
- 새 파트 문서를 만들면 이 표에 한 줄을 추가하고, `common/공통.md` 11장의 반영 현황에도 적는다.
