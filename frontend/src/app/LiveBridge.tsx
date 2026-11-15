import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import {
  emitLive,
  openLiveConnection,
  setLiveState,
  throttle,
  type LiveEventName,
  type Throttled,
} from '@/lib/live'

import { AUTH_STATUS_KEY } from './auth'

/** 이벤트가 오면 다시 불러올 쿼리들 */
const INVALIDATES: Record<LiveEventName, readonly string[]> = {
  hit: ['overview', 'leads'],
  account: ['accounts', 'overview'],
  group: ['groups', 'overview'],
  log: ['logs'],
}

/** 감지는 몰려올 수 있어서, 쿼리 하나를 2초에 한 번만 다시 불러온다. */
const HIT_THROTTLE_MS = 2000
/** 끊겼을 때 로그인 상태를 다시 묻는 간격 */
const AUTH_RECHECK_MS = 15_000

/**
 * 실시간 다리. 콘솔 안쪽(로그인한 화면)에 하나만 둔다. 화면에 그리는 것은 없다.
 *   hit     → ["overview"], ["leads"] (각각 2초에 한 번) + subscribeLive('hit') 로 다시 뿌림
 *   account → ["accounts"], ["overview"]
 *   group   → ["groups"], ["overview"]
 *   log     → ["logs"]
 */
export function LiveBridge() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const invalidate = (key: string) => void queryClient.invalidateQueries({ queryKey: [key] })

    const throttledHit = new Map<string, Throttled>(
      INVALIDATES.hit.map((key) => [key, throttle(() => invalidate(key), HIT_THROTTLE_MS)]),
    )
    const recheckAuth = throttle(
      () => void queryClient.invalidateQueries({ queryKey: AUTH_STATUS_KEY }),
      AUTH_RECHECK_MS,
    )

    const close = openLiveConnection({
      onEvent: (name, payload) => {
        if (name === 'hit') {
          for (const run of throttledHit.values()) run()
        } else {
          for (const key of INVALIDATES[name]) invalidate(key)
        }
        emitLive(name, payload)
      },
      onState: (state, { reconnected }) => {
        setLiveState(state)
        // 끊긴 사이에 놓친 것이 있을 수 있으니 한 번 다 다시 불러온다.
        if (reconnected) {
          for (const key of new Set(Object.values(INVALIDATES).flat())) invalidate(key)
        }
      },
      onDrop: recheckAuth,
    })

    return () => {
      close()
      for (const run of throttledHit.values()) run.cancel()
      recheckAuth.cancel()
      setLiveState('idle')
    }
  }, [queryClient])

  return null
}
