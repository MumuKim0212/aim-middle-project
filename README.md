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
- 첫 실행 때 테이블 37개 자동 생성 + 데모 데이터(`member_001`) 시드
- 메인 화면: 총자산 카드, 대출 배너, 빠른 메뉴, 내 대출 대시보드, 가계부·카드 요약, 대출 상품(칩 필터), 하단 탭·햄버거 메뉴
- 계좌·카드·대출·가계부 탭은 담당자별 빈 페이지

로그인은 아직 없어서 `current_member()`가 데모 회원을 고정으로 돌려줍니다 (`backend/app/main.py`).

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

- 로그인·회원 담당 (`roles.md`에 없음) — `members` 테이블 소유자
- 일반 계좌 테이블 (김연준) — 카드 명세에서 역산한 제안안
- 상세 목록은 `docs/db/db-design.md` 8절
