import { useEffect, useState } from 'react'
import { toApiError, type ApiError } from '../api/errors'

type State<T> = { data?: T; error?: ApiError; loading: boolean }

/** 값을 한 번 불러오는 훅. deps가 바뀌거나 reload()를 부르면 다시 불러온다. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<State<T>>({ loading: true })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let alive = true
    setState({ loading: true })
    fn()
      .then((data) => alive && setState({ data, loading: false }))
      .catch((e) => alive && setState({ error: toApiError(e), loading: false }))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])

  return { ...state, reload: () => setTick((t) => t + 1) }
}
