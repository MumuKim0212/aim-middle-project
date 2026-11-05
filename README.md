# AIM Bank 모바일 웹

은행 모바일 웹서비스 팀 프로젝트의 **메인 페이지 뼈대**입니다. 계좌·카드·가계부·대출 네 영역의 요약을 한 화면에서 보여줍니다.

![메인 페이지](docs/screenshots/home.jpg)

## 구성

| 경로 | 내용 |
|---|---|
| `backend/` | FastAPI + SQLAlchemy 2 + PostgreSQL |
| `frontend/` | React 18 + Vite + TypeScript (모바일 우선, 430px 프레임) |
| `docs/db/db-design.md` | 통합 DB 테이블 설계 (카드·가계부·대출 브랜치 기반) |
| `docs/db/erd.md` | ERD (Mermaid, GitHub에서 바로 렌더링) |
| `docker-compose.yml` | 개발용 PostgreSQL 16 (호스트 포트 5433) |

## 지금 되는 것

- `GET /api/home` — 메인 화면용 요약(계좌 총액, 보유 카드·이번 달 사용액, 가계부 예산 사용률, 내 대출 잔액·다음 납입일, 대출 상품 목록)
- `GET /api/health`
- 첫 실행 때 테이블 자동 생성 + 데모 데이터(시드 사용자 `user1`~`user3`) 시드
- 메인 화면: 총자산 카드, 대출 배너, 빠른 메뉴, 내 대출 대시보드, 가계부·카드 요약, 대출 상품(칩 필터), 하단 탭·햄버거 메뉴
- 계좌·카드·대출·가계부 탭은 담당자별 빈 페이지

회원가입·로그인·로그아웃·간편비밀번호·기기 등록은 `backend/app/auth/` 에 있고, 로그인이 필요한 API 는 모두 `Depends(current_user)` 로 막습니다 (아래 "회원·인증").

## 실행

1. DB

       docker compose up -d

2. 백엔드 (http://127.0.0.1:8000, API 문서 `/docs`)

       cd backend
       python -m venv .venv
       .venv\Scripts\activate
       pip install -r requirements.txt
       uvicorn app.main:app --reload

3. 프론트 (http://127.0.0.1:5173, `/api`는 8000으로 프록시)

       cd frontend
       npm install
       npm run dev

DB 주소를 바꾸려면 `DATABASE_URL`을 지정합니다. 기본값은 `postgresql+psycopg://aimbank:aimbank@localhost:5433/aimbank` 입니다. 데이터를 초기화하려면 `docker compose down -v` 후 다시 올립니다.

## 팀 합의가 필요한 것

- 일반 계좌 테이블 (김연준) — 카드 명세에서 역산한 제안안
- 상세 목록은 `docs/db/db-design.md` 8절

## 회원·인증 (회원·인증 기획서 기준)

- 가입 5단계(`/signup/1~5`) → 자동 로그인 → 간편비밀번호 6자리 설정(건너뛸 수 없음, 이 브라우저를 기기로 등록) → 이용
- 이후 같은 브라우저는 `/login` 에서 간편비밀번호만, 다른 브라우저는 아이디·비밀번호
- 비밀번호 5회 실패 → 10분 잠금, 간편비밀번호 5회 실패 → 아이디·비밀번호 로그인 뒤 재설정해야 풀림
- 세션: 서명된 쿠키, 30분 무활동 시 만료. 로그아웃은 POST 만(기기 쿠키는 유지)
- 로그인이 필요한 API 는 `from app.auth.deps import current_user` 하나로 통일. 모든 조회는 `user.id` 로 필터링하고, 남의 데이터는 404
- 이체 등 중요 동작 직전: `/auth/pin/verify` 화면 + `app.auth.deps.pin_verified(request)` (통과 후 5분)

**시드 사용자 (개발용 값)**

| 아이디 | 비밀번호 | 간편비밀번호 | 용도 |
|---|---|---|---|
| `user1` (김하나) | `Test1234!` | `482915` | 기본 시연용, 가계부·카드·대출 데이터 포함 |
| `user2` (이두리) | `Test5678!` | `739204` | 타인 데이터 접근 차단 테스트용(계좌 1개) |
| `user3` (박세나) | `Test9012!` | 없음 | 첫 로그인 → 간편비밀번호 설정 흐름 테스트용 |

**DB 구조가 바뀌었을 때**(예: `members` → `users`): 기존 로컬 DB 는 새 구조와 안 맞으므로 `python backend/reset_db.py --yes` 로 초기화한다(로컬 개발 DB 의 데이터가 모두 지워진다).

**실패 시나리오 점검**: 시험용 DB 로 서버를 띄우고 `python backend/tests/test_auth_flow.py http://127.0.0.1:8002` (가입·잠금·접근 제어 시나리오 F-01~F-20 가운데 56개 점검). 확인 결과는 `docs/auth-check.md` 에 적었다.
