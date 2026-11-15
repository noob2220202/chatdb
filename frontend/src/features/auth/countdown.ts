import { useEffect, useState } from 'react'

/** 남은 초를 "32초", "4분 5초" 로 적는다. */
export function formatCountdown(totalSeconds: number): string {
  const seconds = Math.max(0, Math.ceil(totalSeconds))
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes}분 ${rest}초` : `${minutes}분`
}

/** until(ms 시각)까지 남은 초. 지났거나 null 이면 0. */
export function secondsUntil(until: number | null, now: number): number {
  if (until === null) return 0
  return Math.max(0, Math.ceil((until - now) / 1000))
}

/** until 까지 남은 초를 1초마다 새로 알려 준다. 지나면 0 에서 멈춘다. */
export function useCountdown(until: number | null): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (until === null) return
    const tick = () => setNow(Date.now())
    const first = window.setTimeout(tick, 0)
    const timer = window.setInterval(tick, 250)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(timer)
    }
  }, [until])

  return secondsUntil(until, now)
}
