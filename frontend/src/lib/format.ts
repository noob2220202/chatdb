/** 숫자·날짜를 한국어 화면에 맞게 표기한다. 모든 함수는 순수 함수다. */

const numberFormat = new Intl.NumberFormat('ko-KR')
const timeFormat = new Intl.DateTimeFormat('ko-KR', { hour: 'numeric', minute: '2-digit', hour12: true })
const monthDayFormat = new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric' })
const fullDateFormat = new Intl.DateTimeFormat('ko-KR', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
})
const yearMonthDayFormat = new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
const weekdayShortFormat = new Intl.DateTimeFormat('ko-KR', { weekday: 'short' })

type DateInput = string | number | Date

function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value)
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** 4812 → "4,812" */
export function formatNumber(value: number): string {
  return numberFormat.format(value)
}

/** 4812, "명" → "4,812명" */
export function formatCount(value: number, unit: string): string {
  return `${numberFormat.format(value)}${unit}`
}

/** "오후 2:14" */
export function formatTime(value: DateInput): string {
  return timeFormat.format(toDate(value))
}

/** "2026년 11월 15일 일요일" */
export function formatFullDate(value: DateInput): string {
  return fullDateFormat.format(toDate(value))
}

/** 올해면 "11월 15일", 다른 해면 "2025년 11월 15일" */
export function formatDay(value: DateInput, now: Date = new Date()): string {
  const date = toDate(value)
  return date.getFullYear() === now.getFullYear()
    ? monthDayFormat.format(date)
    : yearMonthDayFormat.format(date)
}

/** "11월 15일 오후 2:14" (오늘이면 "오늘 오후 2:14", 어제면 "어제 오후 2:14") */
export function formatDateTime(value: DateInput, now: Date = new Date()): string {
  const date = toDate(value)
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
  const time = timeFormat.format(date)
  if (dayDiff === 0) return `오늘 ${time}`
  if (dayDiff === 1) return `어제 ${time}`
  return `${formatDay(date, now)} ${time}`
}

/** "방금", "3분 전", "2시간 전", "어제", "3일 전", 그보다 오래되면 날짜 */
export function formatRelative(value: DateInput, now: Date = new Date()): string {
  const date = toDate(value)
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000)
  if (seconds < 45) return '방금'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 1) return '방금'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)
  if (dayDiff <= 1) return '어제'
  if (dayDiff < 7) return `${dayDiff}일 전`
  return formatDay(date, now)
}

/** 초 → "40초", "14분", "1시간 20분", "2일 3시간" */
export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds))
  if (seconds < 60) return `${seconds}초`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}분`
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  if (hours < 24) return restMinutes ? `${hours}시간 ${restMinutes}분` : `${hours}시간`
  const days = Math.floor(hours / 24)
  const restHours = hours % 24
  return restHours ? `${days}일 ${restHours}시간` : `${days}일`
}

/** 미래 시각까지 남은 시간. 이미 지났으면 null. "14분 뒤" */
export function formatUntil(value: DateInput, now: Date = new Date()): string | null {
  const seconds = (toDate(value).getTime() - now.getTime()) / 1000
  if (seconds <= 0) return null
  return `${formatDuration(seconds)} 뒤`
}

/** 기간(시간 단위)을 읽기 좋게: 24 → "24시간", 72 → "3일", 168 → "7일" */
export function formatWindow(hours: number): string {
  if (hours >= 48 && hours % 24 === 0) return `${hours / 24}일`
  return `${hours}시간`
}

/** 차트 축용 날짜: "11/15" */
export function formatAxisDay(isoDate: string): string {
  const [, month, day] = isoDate.split('-')
  return `${Number(month)}/${Number(day)}`
}

/** "2026-11-15" → "11월 15일 (일)" */
export function formatIsoDay(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  const date = new Date(year ?? 1970, (month ?? 1) - 1, day ?? 1)
  return `${monthDayFormat.format(date)} (${weekdayShortFormat.format(date)})`
}

/** 증감을 문장으로: (128, 105) → "어제보다 23명 많아요" */
export function formatDelta(today: number, yesterday: number, unit = '명'): string {
  const diff = today - yesterday
  if (diff === 0) return '어제와 같아요'
  return diff > 0
    ? `어제보다 ${formatCount(diff, unit)} 많아요`
    : `어제보다 ${formatCount(-diff, unit)} 적어요`
}
