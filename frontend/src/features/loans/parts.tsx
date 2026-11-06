import { errCode } from '../accounts/api'
import { LoadState } from '../accounts/parts'

/** LoadState 에 없는 대출(404 LOAN_NOT_FOUND, 남의 대출 포함)을 더해 보여 준다. */
export function LoanLoad({ error, retry }: { error: unknown; retry: () => void }) {
  if (errCode(error) === 'LOAN_NOT_FOUND') return <div className="state">대출을 찾을 수 없어요.</div>
  return <LoadState error={error} retry={retry} />
}
