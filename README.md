# AIM Bank 모바일 웹 — 가계부 · 회원/인증 (`feature/ledger-app`)

은행 모바일 웹서비스 팀 프로젝트 중 **가계부**와 **회원·인증**을 담은 브랜치입니다.
FastAPI + SQLAlchemy 2 + PostgreSQL / React 18 + Vite + TypeScript (모바일 우선, 420px 프레임).

<img src="docs/screenshots/home.jpg" alt="메인 페이지" width="260">

## 화면

| 로그인 | 가입(1/5) | 간편 로그인 | 내 정보 |
|:--:|:--:|:--:|:--:|
| <img src="docs/screenshots/auth-1-login.jpg" width="170"> | <img src="docs/screenshots/auth-2-signup.jpg" width="170"> | <img src="docs/screenshots/auth-3-pin-login.jpg" width="170"> | <img src="docs/screenshots/auth-4-my-info.jpg" width="170"> |

| 요약(싸가지) | 요약(착한) | 물어보기 | 소비 내역 |
|:--:|:--:|:--:|:--:|
| <img src="docs/screenshots/ledger-1-summary-roast.jpg" width="170"> | <img src="docs/screenshots/ledger-2-summary-kind.jpg" width="170"> | <img src="docs/screenshots/ledger-3-chat.jpg" width="170"> | <img src="docs/screenshots/ledger-4-history.jpg" width="170"> |

| 분석(추이) | 기록 추가 | 사용법 | 로그인 후 홈 |
|:--:|:--:|:--:|:--:|
| <img src="docs/screenshots/ledger-5-analysis.jpg" width="170"> | <img src="docs/screenshots/ledger-6-add-record.jpg" width="170"> | <img src="docs/screenshots/ledger-7-guide.jpg" width="170"> | <img src="docs/screenshots/home-dashboard.jpg" width="170"> |

## 이 브랜치에 있는 것

| 영역 | 내용 |
|---|---|
| **회원·인증** | 회원가입 5단계, 아이디·비밀번호 로그인(5회 실패 10분 잠금), 간편비밀번호 6자리 + 기기 등록 쿠키, 30분 세션, 2차 인증, 비밀번호·간편비밀번호 변경, 로그아웃 |
| **가계부** | 요약, 자연어 물어보기(4가지 말투), 소비 내역(달력·추이·예산 설정), 지출·수입 기록, 카드 거래 자동 분류 |

## 실행

1. DB (PostgreSQL 16, 호스트 포트 5432)

       docker compose up -d

2. 백엔드 (http://127.0.0.1:8000, API 문서 `/docs`)

       cd backend
       python -m venv .venv
       .venv\Scripts\activate
       pip install -r requirements.txt
       copy .env.example .env      # 필요하면 값 수정
       uvicorn app.main:app --reload

3. 프론트 (http://localhost:5173, `/api` 는 8000 으로 프록시)

       cd frontend
       npm install
       npm run dev

첫 실행 때 테이블이 만들어지고 시드 데이터가 들어갑니다.
**테이블 구조가 바뀐 뒤 처음 받았다면** 기존 로컬 DB 는 새 구조와 맞지 않으니 `python backend/reset_db.py --yes` 로 초기화하세요(로컬 개발 DB 의 데이터가 모두 지워집니다).

### 환경변수 (`backend/.env`)

| 이름 | 설명 |
|---|---|
| `DATABASE_URL` | 기본 `postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank` |
| `SESSION_SECRET` | 세션 쿠키 서명 키. 비워 두면 개발용 기본값을 쓰니 **배포 전에 꼭 지정** |
| `LEDGER_NLU` | `rules`(키 없이 규칙 해석만) / `llm`(Gemini 먼저, 실패하면 규칙) |
| `GEMINI_API_KEY` | 가계부 자연어·영수증·자유 질문에 쓰는 키. 없어도 나머지는 동작 |

## 시드 사용자 (개발용 값)

| 아이디 | 비밀번호 | 간편비밀번호 | 용도 |
|---|---|---|---|
| `user1` (김하나) | `Test1234!` | `482915` | 기본 시연용. 가계부·카드·대출 데이터 포함 |
| `user2` (이두리) | `Test5678!` | `739204` | 타인 데이터 접근 차단 테스트용 |
| `user3` (박세나) | `Test9012!` | 없음 | 첫 로그인 → 간편비밀번호 설정 흐름 테스트용 |
| `user4` (최아란) | `Test3456!` | `264817` | 만 19세 미만(2008-06-01). 카드 신청 자격 테스트용 |

## 화면

| 경로 | 화면 | 로그인 |
|---|---|---|
| `/` | 시작 화면(소개·로그인 안내) | 불필요 |
| `/home` | 로그인 후 홈(계좌·대출·가계부·카드 요약) | 필요 |
| `/signup/1~5`, `/login`, `/auth/reset` | 가입 · 로그인 · 비밀번호 재설정 안내 | 불필요 |
| `/auth/pin/setup`, `/auth/pin/verify` | 간편비밀번호 설정 · 2차 인증 | 필요 |
| `/me`, `/me/password`, `/me/pin` | 내 정보 · 비밀번호 변경 · 간편비밀번호 변경 | 필요 |
| `/ledger`, `/ledger/chat`, `/ledger/history` | 가계부 요약 · 물어보기 · 소비 내역 | 필요 |
| `/accounts`, `/cards`, `/loans` | 각 담당자 화면(빈 페이지) | 필요 |

로그인이 필요한 API 는 모두 `Depends(current_user)`(`backend/app/auth/deps.py`) 하나로 막고, 모든 조회는 `user.id` 로 걸러서 남의 데이터는 404 로 답합니다. 오류 응답은 `{"code", "message"}` 모양입니다. 이체 같은 중요 동작 직전에는 `/auth/pin/verify` 를 거치고 서버는 `pin_verified(request)` 로 5분간 통과 여부를 확인합니다.

## 가계부 한눈에

- **요약**: 남은 예산·예상 잔액, 오늘 쓸 수 있는 돈, 소진 예측, 목표 저축, 결제 전 확인, 분류별 예산
- **물어보기**: 말로 묻고 기록합니다(`어제 치킨 2만원 썼어`, `월급 300만원 들어왔어`, `이번 주 얼마 썼어?`). 싸가지·기본·착한·숫자만 4가지 말투, 모드마다 대화가 따로입니다. 오른쪽 위 `?` 에 사용법이 있습니다.
- **소비 내역**: 월별 달력, 6개월 추이, 고정지출 후보, 계좌 출금·수입, CSV, 영수증 사진 입력, 예산 설정. 기록은 오른쪽 아래 `＋` 버튼
- **구조**: 질문 해석은 규칙 + Gemini, 숫자 계산과 판정은 서버가 확정하고 LLM 은 말투만 입힙니다(답변의 숫자는 서버 값과 대조). 정해진 질문이 아니면 읽기 전용 SQL 로 풀되 가상 표만 보는 읽기 전용 DB 역할, 쿼리 검사, 시간·행 제한을 둡니다(`backend/app/ledger_query.py`).

## 테스트

    cd backend
    python tests/test_ledger_nlu.py          # 질문 해석 문장 세트
    python tests/test_ledger_query.py        # 자유 질문 SQL 검사(위험한 쿼리 거부)
    python tests/test_ledger_categorize.py   # 카드 거래 자동 분류 규칙

인증 시나리오(가입·잠금·접근 제어)는 **시험용 DB** 로 서버를 띄워서 돌립니다(DB 를 바꾸는 시나리오가 있습니다).

    DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank_authtest python -m uvicorn app.main:app --port 8002
    python tests/test_auth_flow.py http://127.0.0.1:8002

## 문서

| 경로 | 내용 |
|---|---|
| `docs/db/db-design.md`, `docs/db/erd.md` | 통합 DB 설계(회원은 `users`, 모든 참조는 `user_id`) |
| `docs/auth-check.md` | 인증 실패 시나리오(F-01~F-21) 확인 결과 |
| `docs/screenshots/` | 화면 캡처 |

## 아직 없는 것

- 휴대폰 번호 수정(AUTH-06), 자연어 인증 의도("로그아웃 해줘" 등)와 로그인 전 대화 처리
- 계좌·카드·대출 화면(담당자 구현 대기) — 합칠 때 `member_id` → `user_id` 이름 변경이 필요합니다
