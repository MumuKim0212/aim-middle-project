import { useEffect } from 'react'

type Props = {
  onClose: () => void
  /** 예시 문장을 눌렀을 때: 물어보기 입력칸에 채워 준다(바로 보내지는 않는다) */
  onTry: (text: string) => void
}

const EXAMPLES: { title: string; items: string[] }[] = [
  { title: '결제해도 되는지', items: ['오늘 배달 3만원 시켜도 돼?', '190,000원 결제해도 돼?'] },
  { title: '쓴 돈 기록', items: ['어제 치킨 2만원 썼어', '교육비로 2만원 등록', '등록했어?'] },
  { title: '들어온 돈 기록', items: ['월급 300만원 들어왔어', '5만원 용돈 받았어'] },
  { title: '확인하기', items: ['오늘 얼마 쓸 수 있어?', '남은 예산 알려줘', '이번 주 얼마 썼어?', '이번 달 외식 얼마 썼어?', '지난달엔?'] },
  { title: '자유롭게 물어보기', items: ['요일별로 얼마씩 썼는지 보여줘', '분류별로 제일 많이 쓴 순위 알려줘'] },
]

const TABS: { name: string; points: string[] }[] = [
  {
    name: '요약',
    points: [
      '남은 예산·계좌 잔액·카드대금 반영 후 예상 잔액',
      '오늘 쓸 수 있는 돈, 이번 달 소진 예측, 무지출 일수',
      '월 예산·분류 예산 경고와 카드대금 알림',
      '이번 달 저축 목표 (결제 전 확인에서 보류로 막은 돈이 쌓여요)',
      '결제 전 확인: 금액을 넣으면 결제해도 되는지 바로 판정',
    ],
  },
  {
    name: '물어보기',
    points: [
      '말로 물어보고, 쓴 돈·들어온 돈도 말로 기록해요',
      '답변은 판정 → 한마디 → 숫자 카드 순서',
      '모드마다 대화가 따로예요 (싸가지·기본·착한·숫자만)',
      '＋ 새 대화로 이 모드의 대화만 비울 수 있어요',
      '정해진 질문이 아니어도 "이렇게 계산했어요"와 함께 답해요',
    ],
  },
  {
    name: '소비 내역',
    points: [
      '내역: 월별 달력(날짜를 누르면 그날 내역), CSV 내려받기, 계좌 출금·수입',
      '분석: 6개월 지출 추이(막대를 누르면 분류별 내역), 고정지출 후보',
      '예산 설정: 월 예산, 분류별 예산, 예정 카드대금',
      '＋ 버튼: 지출·수입 기록, 영수증 사진으로 입력',
      '거래의 분류·금액은 `수정`으로 고칠 수 있어요',
    ],
  },
]

const TIPS = [
  '카드 거래는 사용처 이름으로 분류가 자동으로 채워져요. 틀리면 수정하면 돼요.',
  '새 달이 되면 지난달 예산이 자동으로 이어져요.',
  '위쪽 모드 줄은 어느 탭에서나 바꿀 수 있어요. 싸가지 모드는 욕설 강도도 고를 수 있어요.',
]

/** 가계부 사용법과 기능을 한눈에 보는 창 */
export default function Guide({ onClose, onTry }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="lg-sheet" role="dialog" aria-modal="true" aria-label="가계부 사용법" onClick={onClose}>
      <div className="body lg-guide" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="close" aria-label="닫기" onClick={onClose}>✕</button>
        <h2>가계부 사용법</h2>
        <p className="lead">세 가지 탭으로 나뉘어 있어요. 말로 물어보고 기록하는 게 제일 빨라요.</p>

        <h3>이렇게 물어보세요 <small>눌러서 입력칸에 채워 봐요</small></h3>
        {EXAMPLES.map((g) => (
          <div className="grp" key={g.title}>
            <b>{g.title}</b>
            <div className="chips">
              {g.items.map((t) => <button key={t} type="button" onClick={() => onTry(t)}>{t}</button>)}
            </div>
          </div>
        ))}

        <h3>탭별 기능</h3>
        {TABS.map((t) => (
          <div className="grp" key={t.name}>
            <b>{t.name}</b>
            <ul>{t.points.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        ))}

        <h3>알아 두면 좋아요</h3>
        <ul className="tips">{TIPS.map((p) => <li key={p}>{p}</li>)}</ul>
      </div>
    </div>
  )
}
