/** 카드 비밀번호가 너무 단순한지: 네 자리가 모두 같거나, 인접 자리 차이가 모두 +1 또는 모두 -1 */
export const isSimplePin = (pin: string) => {
  const d = [...pin].map(Number)
  const diffs = d.slice(1).map((v, i) => v - d[i])
  return diffs.every((x) => x === 0) || diffs.every((x) => x === 1) || diffs.every((x) => x === -1)
}
