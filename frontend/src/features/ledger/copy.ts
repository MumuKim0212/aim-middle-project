// 모드별 문구. 가계부_4가지_모드_체험.html 의 문구를 그대로 옮겼다.
// 판정(가능/보류, 위험 단계)은 서버가 계산하고, 여기서는 말투만 입힌다.
import { won } from '../../format'
import type { Check, Entry, Level, Mode, Summary } from './api'

export type { Entry, History, Intent } from './api'

export const MODES: Mode[] = ['roast', 'basic', 'kind', 'numbers']
export const MODE_LABEL: Record<Mode, string> = { roast: '싸가지', basic: '기본', kind: '착한', numbers: '숫자만' }
export const ANSWER_LABEL: Record<Mode, string> = {
  roast: '지옥문 안내',
  basic: '가계부 안내',
  kind: '저금통의 답장',
  numbers: '계산 결과',
}
export const CATEGORIES = ['배달', '외식', '장보기', '쇼핑', '교통', '생활', '기타']
export const LEVEL_LABEL: Record<Level, string> = { safe: '안정', caution: '주의', danger: '경고' }
const DATA_LABEL = 'DATA'

type Hero = { eyebrow: string; title: string[]; sub: string; badge: string }
export const HERO: Record<Mode, Hero> = {
  roast: { eyebrow: '', title: ['지옥문', '입장 직전.'], sub: '지출 경고 · 난이도 급상승', badge: 'GATE LEVEL 03 · 경고' },
  basic: { eyebrow: '이번 달 나의 가계부', title: ['이번 달 돈,', '한눈에 보기'], sub: '잔액과 예정 지출을 함께 확인해요.', badge: '소비 현황 확인' },
  kind: { eyebrow: '내 돈 지킴이 · 오늘의 표정', title: ['배달비에', '비가 온다!'], sub: '남은 예산 같이 지켜보자.', badge: '저금통이 우산 쓰는 중 ☂' },
  numbers: { eyebrow: 'LEDGER / MONTHLY', title: ['MONTHLY', 'STATUS'], sub: '지출 · 잔액 · 예정 카드대금', badge: 'BUDGET STATUS' },
}
export const WARNING_TITLE: Record<Mode, string> = {
  roast: '배달 또 누르면 열린다',
  basic: '배달 지출 주의',
  kind: '조금만 조심하자',
  numbers: '예산 사용 현황',
}
export const REWARD_TITLE: Record<Mode, string> = {
  roast: '오늘의 생존 미션',
  basic: '이번 주 절약 제안',
  kind: '오늘 참으면 칭찬 스탬프 +1',
  numbers: '예산 절감 시뮬레이션',
}
/** typical: 평소 배달 한 번 금액(DB 에서 계산). 금액을 화면에 박아 두지 않는다. */
export const rewardBody = (mode: Mode, typical: number): string =>
  ({
    roast: '배달 한 번 참으면 이번 주 식비 방어 성공. 버텨 봐.',
    basic: '배달을 한 번 줄이면 이번 주 식비에 여유가 생깁니다.',
    kind: '오늘 배달을 아끼면 칭찬 스탬프 +1! 잘할 수 있어.',
    numbers: `배달 ${won(typical)} 미사용 시 예상 잔액 차이 +${won(typical)}.`,
  })[mode]

export type Metrics = {
  budget: number
  spent: number
  remaining: number
  ratio: number
  delivery: number
  deliveryBudget: number
  deliveryRemaining: number
  deliveryRatio: number
  projected: number
  balance: number
}

export function metrics(s: Summary): Metrics {
  const d = s.categories.find((c) => c.category === '배달')
  return {
    budget: s.budget.total,
    spent: s.budget.spent,
    remaining: s.budget.remaining,
    ratio: s.budget.ratio,
    delivery: d?.spent ?? 0,
    deliveryBudget: d?.budget ?? 0,
    deliveryRemaining: d?.remaining ?? 0,
    deliveryRatio: d?.ratio ?? 0,
    projected: s.balance.expected,
    balance: s.balance.current,
  }
}

export function warningLevelLabel(mode: Mode, level: Level): string {
  return mode === 'numbers' ? DATA_LABEL : LEVEL_LABEL[level]
}

export function riskText(mode: Mode, level: Level, m: Metrics): string {
  const safe = level === 'safe'
  const rest = m.deliveryRemaining <= 0
  return {
    roast: safe
      ? '오늘은 괜찮네. 그래도 막 긁지는 마.'
      : `배달 예산 ${m.deliveryRatio}% 썼어. ${rest ? '이제 배달은 예산 밖이야.' : '한 번 더 시키기 전에 카드값부터 봐.'} 정신 차려.`,
    basic: safe
      ? '현재 지출은 설정한 예산 안에 있습니다.'
      : `배달 예산 ${m.deliveryRatio}% 사용했습니다. 결제 전 잔여 예산과 카드대금 반영 후 잔액을 확인해 주세요.`,
    kind: safe
      ? '이번 달 예산을 잘 지키고 있어! 같이 계속 가자.'
      : `배달 예산 ${m.deliveryRatio}% 썼어. 오늘은 집밥 어때? 남은 돈 같이 지키자.`,
    numbers: `월 예산 ${won(m.budget)} / 사용 ${won(m.spent)} / 잔여 ${won(m.remaining)} / 배달 ${won(m.delivery)} / 예상 잔액 ${won(m.projected)}`,
  }[mode]
}

// ───────────── 물어보기 ─────────────

export function answerFor(mode: Mode, e: Entry, s: Summary): string {
  const m = metrics(s)

  if ((e.intent === 'last' || e.intent === 'prev2') && e.history) {
    const { month, spent, delta, topName, topAmount } = e.history
    const more = delta >= 0
    return {
      roast: `${month}에 ${won(spent)} 썼어. ${more ? `전월보다 ${won(delta)} 더 썼고` : `전월보다 ${won(-delta)} 덜 썼고`}, 제일 많이 샌 곳은 ${topName} ${won(topAmount)}.`,
      basic: `${month} 지출은 ${won(spent)}입니다. 전월 대비 ${more ? `${won(delta)} 증가` : `${won(-delta)} 감소`}했고, 최대 지출 항목은 ${topName}입니다.`,
      kind: `${month}에는 ${won(spent)} 썼어. ${delta < 0 ? '전월보다 아꼈네, 잘했어!' : '전월보다 늘었지만 같이 살펴보자.'} 가장 큰 항목은 ${topName}이야.`,
      numbers: `${month} 지출 ${won(spent)} / 전월 대비 ${more ? '+' : ''}${won(delta)} / 최대 항목 ${topName} ${won(topAmount)}`,
    }[mode]
  }

  if (e.intent === 'chat') {
    return {
      roast: '뭐라는 거야. 돈 얘기나 해. 잔액, 예산, 지난달 지출 같은 거 물어보라고.',
      basic: '가계부에 대해 물어봐 주세요. 예: 잔액, 남은 예산, 지난달 지출, 결제 가능 여부',
      kind: '무슨 말인지 잘 모르겠어. 잔액이나 예산, 결제해도 되는지 물어봐 줄래?',
      numbers: '입력 해석 불가. 예: 잔액 / 예산 / 지난달 / 금액 결제',
    }[mode]
  }

  if (e.intent === 'record') {
    const r = e.recorded
    if (!r) {
      return {
        roast: e.recordError ? '기록 못 했어. 카드부터 확인해.' : '얼마 썼는지 말해. 금액 없으면 기록 못 해.',
        basic: e.recordError ? '지출을 기록하지 못했습니다. 사용 중인 카드를 확인해 주세요.' : '쓴 금액을 알려주시면 기록해 드릴게요.',
        kind: e.recordError ? '기록하지 못했어. 카드를 한 번 확인해 줄래?' : '얼마 썼는지 알려줘. 내가 적어 둘게!',
        numbers: e.recordError ? '기록 실패 / 카드 확인 필요' : '금액 필요. 예: 어제 치킨 20,000원',
      }[mode]
    }
    return {
      roast: `${r.when} ${r.category} ${won(r.amount)} 썼네. 적어 놨으니까 다음엔 참아.`,
      basic: `${r.when} ${r.category} ${won(r.amount)} 지출을 기록했습니다.`,
      kind: `${r.when} ${r.category} ${won(r.amount)} 썼구나. 잘 적어 뒀어!`,
      numbers: `기록 완료 / ${r.when} / ${r.category} ${won(r.amount)}`,
    }[mode]
  }

  if (e.intent === 'week' && e.week) {
    const w = e.week
    const more = w.delta >= 0
    return {
      roast: `이번 주 ${won(w.spent)} 썼어. 제일 많이 샌 곳은 ${w.topName} ${won(w.topAmount)}.`,
      basic: `이번 주 지출은 ${won(w.spent)}입니다. 가장 많이 쓴 항목은 ${w.topName} ${won(w.topAmount)}입니다.${w.hasPrev ? ` 지난주 같은 기간보다 ${won(Math.abs(w.delta))} ${more ? '많습니다' : '적습니다'}.` : ''}`,
      kind: `이번 주에는 ${won(w.spent)} 썼어. 가장 큰 항목은 ${w.topName}이야.${w.hasPrev ? (more ? ' 지난주보다 조금 늘었어.' : ' 지난주보다 아꼈네, 잘했어!') : ''}`,
      numbers: `이번 주 지출 ${won(w.spent)} / 최대 항목 ${w.topName} ${won(w.topAmount)}${w.hasPrev ? ` / 지난주 대비 ${more ? '+' : '-'}${won(Math.abs(w.delta))}` : ''}`,
    }[mode]
  }

  if (e.intent === 'category' && e.catSpent) {
    const c = e.catSpent
    const left = c.remaining
    return {
      roast: `이번 달 ${c.category}에 ${won(c.spent)} 썼어.${left === null ? '' : left < 0 ? ` 예산 ${won(-left)} 넘겼고.` : ` 예산은 ${won(left)} 남았어.`}`,
      basic: `이번 달 ${c.category} 지출은 ${won(c.spent)}입니다.${left === null ? '' : left < 0 ? ` 예산을 ${won(-left)} 초과했습니다.` : ` 예산은 ${won(left)} 남았습니다.`}`,
      kind: `이번 달 ${c.category}에는 ${won(c.spent)} 썼어.${left === null ? '' : left < 0 ? ` 예산을 ${won(-left)} 넘겼으니 조금만 조절해 보자.` : ` 예산이 ${won(left)} 남았으니 괜찮아!`}`,
      numbers: `${c.category} 지출 ${won(c.spent)}${c.budget === null ? '' : ` / 예산 ${won(c.budget)} / 잔여 ${won(left ?? 0)}`}`,
    }[mode]
  }

  if (e.intent === 'balance') {
    return {
      roast: `계좌 ${won(m.balance)} 보여도 다 네 돈 아니야. 카드값 빼면 ${won(m.projected)} 남아.`,
      basic: `계좌 잔액은 ${won(m.balance)}, 카드대금 반영 후 예상 잔액은 ${won(m.projected)}입니다.`,
      kind: `계좌엔 ${won(m.balance)} 있어. 카드값까지 생각하면 ${won(m.projected)} 남으니까 같이 조심하자.`,
      numbers: `계좌 ${won(m.balance)} / 카드대금 반영 후 ${won(m.projected)}`,
    }[mode]
  }

  if (e.intent === 'budget') {
    return {
      roast: `남은 예산 ${won(m.remaining)}. 배달엔 ${won(m.deliveryRemaining)}밖에 안 남았어.`,
      basic: `이번 달 남은 예산은 ${won(m.remaining)}이며 배달 예산은 ${won(m.deliveryRemaining)} 남았습니다.`,
      kind: `이번 달 ${won(m.remaining)} 남았어. 배달은 ${won(m.deliveryRemaining)} 남았으니 조금만 조심하자.`,
      numbers: `월 잔여 ${won(m.remaining)} / 배달 잔여 ${won(m.deliveryRemaining)} / 사용률 ${m.ratio}%`,
    }[mode]
  }

  if (e.amount === null || !e.check) {
    return {
      roast: '얼마 쓸 건지 말해. 금액 없으면 계산 못 해.',
      basic: '사용할 금액을 알려주시면 남은 예산을 계산해 드릴게요.',
      kind: '얼마 쓰고 싶은지 알려줘! 같이 확인해 보자.',
      numbers: '금액 필요. 예: 20,000원',
    }[mode]
  }

  const { check } = e
  const amount = e.amount
  if (check.result === 'held') {
    // 답변에서는 카테고리 예산 → 월 예산 → 예상 잔액 순으로 사유를 고른다(시안과 동일).
    const reason = check.reasons.includes('CATEGORY_BUDGET')
      ? `${e.category} 예산`
      : check.reasons.includes('MONTH_BUDGET')
        ? '월 예산'
        : '예상 잔액'
    return {
      roast: `${won(amount)}? ${reason} 넘는다. 정신 차려. 이 결제는 보류야.`,
      basic: `${won(amount)} 결제 시 ${reason}을 초과합니다. 시뮬레이션에서 결제를 보류했습니다.`,
      kind: `${won(amount)}은 지금 ${reason}을 넘어서 잠깐 멈춰 줄게. 금액을 줄여 볼까?`,
      numbers: `요청 ${won(amount)} / 사유 ${reason} 초과 / 상태 보류`,
    }[mode]
  }
  const { budgetRemaining, expectedBalance } = check.after
  return {
    roast: `${won(amount)} 쓰면 카드값 내고 ${won(expectedBalance)} 남아.${e.category === '배달' ? ' 배달 또 먹을 거야? 예산부터 봐.' : ' 남은 돈 생각하고 결정해.'}`,
    basic: `${won(amount)} 사용 시 월 예산 ${won(budgetRemaining)}, 카드대금 반영 후 ${won(expectedBalance)}이 예상됩니다.`,
    kind: `${won(amount)} 쓰면 예산 ${won(budgetRemaining)} 남아. 카드값까지 생각해 보고 정하자.`,
    numbers: `요청 ${won(amount)} / 월 예산 잔여 ${won(budgetRemaining)} / 예상 잔액 ${won(expectedBalance)} / 상태 가능`,
  }[mode]
}

/** 결제 전 확인 폼의 피드백 (시안의 blockReason 순서: 월 예산 → 예상 잔액 → 카테고리 예산) */
export function paymentFeedback(c: Check): { blocked: boolean; text: string } {
  const r = c.reasons[0]
  if (!r) {
    return {
      blocked: false,
      text: `결제 가능 · ${won(c.amount)} 사용 시 월 예산 ${won(c.after.budgetRemaining)} 남음. 소비 내역 탭에서 지출을 기록할 수 있어요.`,
    }
  }
  const lim = c.limits[r] ?? 0
  const why =
    r === 'MONTH_BUDGET'
      ? lim <= 0 ? '월 예산을 이미 초과했습니다.' : `월 예산 잔여 ${won(lim)}을 넘습니다.`
      : r === 'BALANCE'
        ? lim <= 0 ? '카드대금 반영 후 예상 잔액이 없습니다.' : `카드대금 반영 후 예상 잔액 ${won(lim)}을 넘습니다.`
        : lim <= 0 ? `${c.category} 예산을 이미 초과했습니다.` : `${c.category} 예산 잔여 ${won(lim)}을 넘습니다.`
  return { blocked: true, text: `결제 보류 · ${why} 실제 카드 결제는 진행되지 않았습니다.` }
}

/** 요약 탭의 소진 예측 한 줄. 서버가 계산한 값(forecast)만 말투를 입혀 쓴다. */
export function forecastText(mode: Mode, f: NonNullable<Summary['forecast']>, budget: number): string | null {
  if (budget <= 0) return null
  if (f.over) {
    return {
      roast: '이미 예산 다 썼어. 더 쓰면 그냥 빚이야.',
      basic: '이번 달 예산을 이미 모두 사용했습니다.',
      kind: '이번 달 예산을 다 썼어. 남은 날은 같이 아껴 보자!',
      numbers: '예산 소진 / 상태 초과',
    }[mode]
  }
  if (f.runOutDay !== null) {
    const d = f.runOutDay
    return {
      roast: `지금 속도면 ${d}일에 예산 바닥. 정신 차려.`,
      basic: `현재 속도라면 ${d}일에 월 예산을 모두 사용합니다.`,
      kind: `이 속도면 ${d}일쯤 예산이 다 찰 것 같아. 조금만 조절해 볼까?`,
      numbers: `소진 예상일 ${d}일 / 월말 예상 지출 ${won(f.projected)}`,
    }[mode]
  }
  return {
    roast: `월말 예상 ${won(f.projected)}. 이대로면 겨우 버텨.`,
    basic: `월말 예상 지출은 ${won(f.projected)}으로 예산 안에서 마무리됩니다.`,
    kind: `월말까지 ${won(f.projected)} 쓸 것 같아. 예산 안이라 잘하고 있어!`,
    numbers: `월말 예상 지출 ${won(f.projected)} / 예산 내`,
  }[mode]
}

export const STAT_LABEL: Record<Mode, { saved: string; streak: string }> = {
  roast: { saved: '참아서 막은 돈', streak: '안 쓴 날 연속' },
  basic: { saved: '보류로 막은 결제', streak: '무지출 연속' },
  kind: { saved: '참아 낸 금액', streak: '무지출 스탬프' },
  numbers: { saved: '보류 합계', streak: '무지출 일수' },
}
