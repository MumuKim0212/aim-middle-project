# AIM Bank 모바일 웹

은행 모바일 웹서비스 팀 프로젝트입니다. 계좌·카드·가계부·대출·회원/인증 영역을 한 앱에서 보여줍니다.
FastAPI + SQLAlchemy 2 + PostgreSQL / React 18 + Vite + TypeScript (모바일 우선, 420px 프레임).
기획 문서는 [docs/README.md](docs/README.md)에서 시작합니다. 규칙의 기준은 [docs/common/공통.md](docs/common/공통.md)입니다.

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

## 구성

| 경로 | 내용 |
|---|---|
| `backend/` | FastAPI + SQLAlchemy 2 + PostgreSQL |
| `frontend/` | React 18 + Vite + TypeScript (모바일 우선, 420px 프레임) |
| `docs/README.md` | 기획·설계 문서 목차 (공통, 기술스택, 오류코드, 인증, 계좌, 카드) |
| `docs/db/db-design.md` | 통합 DB 테이블 설계 (기획 문서 기준) |
| `docs/db/erd.md` | ERD (Mermaid, GitHub에서 바로 렌더링) |
| `docker-compose.yml` | 개발용 PostgreSQL 17 + pgvector (호스트 포트 5432) |

## 지금 되는 것

| 영역 | 내용 |
|---|---|
| **회원·인증** | 회원가입 5단계, 아이디·비밀번호 로그인(5회 실패 10분 잠금), 간편비밀번호 6자리 + 기기 등록 쿠키, 30분 세션, 2차 인증, 비밀번호·간편비밀번호 변경, 로그아웃 |
| **가계부** | 요약, 자연어 물어보기(4가지 말투), 소비 내역(달력·추이·예산 설정), 지출·수입 기록, 카드 거래 자동 분류 |
| **카드** | 내 카드 목록·상세, 이용내역(필터·페이지 나누기), 결제 예정 금액, 정지·해제·분실 신고, 카드 신청(신용·체크, 중복 신청 방지), 해지. 쓰기 동작은 간편비밀번호 재확인(S-08 팝업) 뒤에 실행 |
| **계좌** | 저축예금·정기예금·정기적금 개설, 계좌 목록·상세·거래 내역, 이체(간편비밀번호 재확인), 해지, 이자 조회, 자동이체 배치 (`/api/accounts`) |
| **대출** | 상품 목록, 신청 단계 전체(동의·적합성·증빙·심사·추천·조건·약정·실행), 내 대출 조회·중도상환·청약철회·금리인하요구·기간연장·증명서 (`/api/loans`). 실행·중도상환·철회는 내 계좌에서 입출금되고 간편비밀번호 재확인이 필요 ([docs/loan](docs/loan/README.md)) |
| **홈** | `GET /api/home` — 계좌 총액, 보유 카드·이번 달 사용액, 가계부 예산 사용률, 내 대출 잔액·다음 납입일, 대출 상품 목록. 하단 탭·햄버거 메뉴 |

- `GET /api/health`
- 계좌 화면(`/accounts`)은 있고, 대출 화면(`/loans`)은 담당자별 빈 페이지입니다. 대출 API는 먼저 만들어 두었습니다.

## 실행

1. DB (PostgreSQL 17 + pgvector, 호스트 포트 5432)

       docker compose up -d

2. 백엔드 (http://127.0.0.1:8000, API 문서 `/docs`)

       cd backend
       python -m venv .venv
       .venv\Scripts\activate
       pip install -r requirements.txt
       copy .env.example .env      # 필요하면 값 수정
       alembic upgrade head        # 테이블 만들기·갱신 (코드를 받을 때마다)
       uvicorn app.main:app --reload

3. 프론트 (http://localhost:5173, `/api` 는 8000 으로 프록시)

       cd frontend
       npm install
       npm run dev

DB 주소를 바꾸려면 `DATABASE_URL`을 지정합니다. 기본값은 `postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank` 입니다.
테이블은 Alembic 마이그레이션(`backend/alembic/`)이 만들고, 시드 데이터는 서버가 처음 켜질 때 들어갑니다. DB 가 최신 마이그레이션이 아니면 서버가 시작하지 않고 할 일을 알려 줍니다.
- **코드를 받았는데 테이블 구조가 바뀌었다면**: `alembic upgrade head` 한 번이면 됩니다. 데이터는 그대로 남습니다.
- **마이그레이션 도입 전부터 쓰던 로컬 DB**(서버가 시작할 때 테이블을 만들던 시절): 대출 통합(2026-11-06) 이후 구조라면 `alembic stamp head` 로 "최신"이라고 표시만 하면 됩니다. 그보다 오래됐다면 `python backend/reset_db.py --yes` 로 초기화하세요(로컬 개발 DB 의 데이터가 모두 지워집니다).
- **모델을 고쳤다면**: `alembic revision --autogenerate -m "설명"` → 만들어진 파일을 확인·수정 → `alembic upgrade head`. 대출 테이블은 모델이 없어 SQL 로 마이그레이션을 직접 쓰고 `backend/app/loan/schema.sql` 도 같이 고칩니다. `python -m pytest backend/tests/test_migrations.py` 가 모델·schema.sql 과 마이그레이션이 어긋나면 알려 줍니다.
- DB 컨테이너가 예전 PostgreSQL 16이면 `docker compose down -v` 로 볼륨을 지우고 다시 올립니다.

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
| `/products` | 상품 안내(저축예금·정기예금·정기적금) | 불필요 |
| `/accounts`, `/accounts/:id`(+`/transactions` `/deposit` `/pay` `/close`), `/products/:type/open`, `/transfer` | 계좌 목록·상세·개설·이체·해지 (계좌.md) | 필요 |
| `/cards`, `/cards/:id`, `/cards/transactions`, `/cards/billing`, `/cards/apply` 등 | 카드 | 필요 |
| `/loans` | 담당자 화면(빈 페이지) | 필요 |

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
    python tests/test_card_cycles.py         # 카드 결제 주기·한도 계산

인증 시나리오(가입·잠금·접근 제어)는 **시험용 DB** 로 서버를 띄워서 돌립니다(DB 를 바꾸는 시나리오가 있습니다).

    DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank_authtest alembic upgrade head
    DATABASE_URL=postgresql+psycopg://aimbank:aimbank@localhost:5432/aimbank_authtest python -m uvicorn app.main:app --port 8002
    python tests/test_auth_flow.py http://127.0.0.1:8002

카드 API 시나리오(조회·정지·신청·해지)는 임시 DB(`cardtest`)와 임시 서버(8001)를 스스로 띄우고 끝나면 지웁니다. PostgreSQL 이 떠 있어야 합니다.

    cd backend
    python -m tests.card_api_scenarios

## 문서

| 경로 | 내용 |
|---|---|
| `docs/README.md` | 문서 목차와 읽는 순서 |
| `docs/common/` | 공통 규칙(공통.md), 오류 코드, 기술 스택 |
| `docs/auth/`, `docs/account/`, `docs/card/` | 파트별 기획서. 인증 실패 시나리오 확인 결과는 `docs/auth/auth-check.md` |
| `docs/db/db-design.md`, `docs/db/erd.md` | 통합 DB 설계(회원은 `users`, 모든 참조는 `user_id`) |
| `docs/screenshots/` | 화면 캡처 |

## 아직 없는 것

- 휴대폰 번호 수정(AUTH-06), 자연어 인증 의도("로그아웃 해줘" 등)와 로그인 전 대화 처리
- 대출 화면(담당자 구현 대기, API는 `/api/loans`). 대출 자연어 의도(`loan` 에이전트)도 아직 없습니다
