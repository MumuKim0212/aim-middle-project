# 가계부 기능 제안 및 시안

은행 모바일 웹 프로젝트의 가계부 담당 자료입니다.

## 파일

- [가계부 기획안](가계부_기획안.md) · [HTML로 보기](가계부_기획안.html)
- [4가지 모드 체험 HTML](가계부_4가지_모드_체험.html): 말투·화면 전환과 간단한 가계부 기능
- [디자인 3종 비교 HTML](가계부_디자인_3종_비교.html): 지옥문, 일반 은행형, 귀여운 저금통형 이미지 비교
- `assets/`: 두 HTML에서 공통으로 사용하는 이미지
- `screenshots/`: 네 가지 말투 모드, 디자인 비교, 기획안과 TIL HTML의 실제 브라우저 캡처

## 화면 캡처

| 화면 | 캡처 |
|---|---|
| 싸가지 모드 | [01_roast.jpg](screenshots/01_roast.jpg) |
| 기본 모드 | [02_basic.jpg](screenshots/02_basic.jpg) |
| 착한 모드 | [03_kind.jpg](screenshots/03_kind.jpg) |
| 숫자만 모드 | [04_numbers.jpg](screenshots/04_numbers.jpg) |
| 디자인 3종 비교 | [05_design_comparison.jpg](screenshots/05_design_comparison.jpg) |
| 가계부 기획안 HTML | [06_plan_html.jpg](screenshots/06_plan_html.jpg) |
| TIL·티스토리용 HTML 미리보기 | [07_tistory_html.jpg](screenshots/07_tistory_html.jpg) |

## 실행

`가계부_4가지_모드_체험.html`을 브라우저에서 열면 됩니다. 이미지가 보이도록 `assets` 폴더를 HTML과 같은 위치에 두세요. 로컬 서버를 쓰려면 레포 루트에서 `python -m http.server 8765` 실행 후 `http://127.0.0.1:8765/Proposal/Ledger/가계부_4가지_모드_체험.html`에 접속하세요.

## 바로 확인할 흐름

1. `싸가지 / 기본 / 착한 / 숫자만`을 눌러 화면과 답변이 함께 바뀌는지 확인합니다.
2. `20만 원 결제?`를 눌러 예산 초과 보류를 확인합니다.
3. `소비 내역`에서 지출을 추가하고 요약 화면의 남은 예산이 바뀌는지 확인합니다.
4. 조회 월을 지난달로 바꿔 소비를 비교합니다.
5. 예산을 수정하고 새로고침해 설정과 기록이 유지되는지 확인합니다.

데모는 브라우저 `localStorage`와 예시 데이터로만 작동합니다. 실제 은행 계좌, 카드 승인, AI/RAG 서버는 연결되어 있지 않습니다.
