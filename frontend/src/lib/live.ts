/**
 * 실시간 연결. 서버의 /api/stream(SSE)을 하나만 열어 두고, 들어온 이벤트를 앱 안에 다시 뿌린다.
 *
 *   const off = subscribeLive('hit', (hit) => { … })   // 화면에서 이벤트 받기
 *   const state = useLiveState()                        // 'open' 이면 받는 중
 *
 * 연결을 여닫는 일은 src/app/LiveBridge.tsx 가 한다.
 */
import { useSyncExternalStore } from 'react'

/** 서버가 보내는 이벤트 이름. 본문은 schemas 의 *Out 모델을 JSON 으로 옮긴 것이다. */
export type LiveEventName = 'hit' | 'account' | 'group' | 'log'
export type LivePayload = Record<string, unknown>
export const LIVE_EVENTS: readonly LiveEventName[] = ['hit', 'account', 'group', 'log']

/** idle: 아직 열지 않음 / connecting: 여는 중·다시 잇는 중 / open: 받는 중 */
export type LiveState = 'idle' | 'connecting' | 'open'

// ── 작은 이벤트 배분기 ─────────────────────────────────────────

type Listener<T> = (payload: T) => void

export type Emitter<M> = {
  on<K extends keyof M>(name: K, listener: Listener<M[K]>): () => void
  emit<K extends keyof M>(name: K, payload: M[K]): void
}

export function createEmitter<M>(): Emitter<M> {
  const listeners = new Map<keyof M, Set<Listener<never>>>()
  return {
    on(name, listener) {
      let set = listeners.get(name)
      if (!set) {
        set = new Set()
        listeners.set(name, set)
      }
      set.add(listener as Listener<never>)
      return () => {
        set.delete(listener as Listener<never>)
      }
    },
    emit(name, payload) {
      const set = listeners.get(name)
      if (!set) return
      // 듣는 쪽 하나가 실패해도 나머지는 받는다.
      for (const listener of [...set]) {
        try {
          ;(listener as Listener<unknown>)(payload)
        } catch (error) {
          console.error(error)
        }
      }
    },
  }
}

type LiveEvents = Record<LiveEventName, LivePayload>
const events = createEmitter<LiveEvents>()

/** 실시간 이벤트를 듣는다. 돌려받은 함수를 부르면 그만 듣는다. */
export function subscribeLive(
  name: LiveEventName,
  listener: (payload: LivePayload) => void,
): () => void {
  return events.on(name, listener)
}

/** 이벤트를 앱 안에 뿌린다. LiveBridge 와 시험에서만 쓴다. */
export function emitLive(name: LiveEventName, payload: LivePayload): void {
  events.emit(name, payload)
}

// ── 연결 상태 ──────────────────────────────────────────────────

let liveState: LiveState = 'idle'
const stateListeners = new Set<() => void>()

export function getLiveState(): LiveState {
  return liveState
}

export function setLiveState(next: LiveState): void {
  if (next === liveState) return
  liveState = next
  for (const listener of [...stateListeners]) listener()
}

export function subscribeLiveState(listener: () => void): () => void {
  stateListeners.add(listener)
  return () => {
    stateListeners.delete(listener)
  }
}

/** 지금 연결 상태. 'open' 일 때만 "받는 중"이다. */
export function useLiveState(): LiveState {
  return useSyncExternalStore(subscribeLiveState, getLiveState, getLiveState)
}

// ── 묶어 보내기 ────────────────────────────────────────────────

export type Throttled = {
  (): void
  /** 기다리던 호출을 버린다 */
  cancel(): void
}

/**
 * wait 밀리초에 한 번만 부르도록 묶는다. 첫 호출은 바로 나가고,
 * 그 사이에 온 호출은 몇 번이든 구간이 끝날 때 한 번으로 합쳐진다.
 */
export function throttle(fn: () => void, wait: number): Throttled {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending = false

  const open = () => {
    timer = setTimeout(() => {
      timer = null
      if (pending) {
        pending = false
        fn()
        open()
      }
    }, wait)
  }

  const throttled = () => {
    if (timer !== null) {
      pending = true
      return
    }
    fn()
    open()
  }
  throttled.cancel = () => {
    if (timer !== null) clearTimeout(timer)
    timer = null
    pending = false
  }
  return throttled
}

// ── 다시 잇기 ──────────────────────────────────────────────────

/** n번째(0부터) 다시 잇기 전에 기다릴 시간: 1초, 2초, 4초 … 최대 30초 */
export function backoffDelay(attempt: number, base = 1000, max = 30_000): number {
  return Math.min(max, base * 2 ** Math.max(0, attempt))
}

/** EventSource 가운데 여기서 쓰는 부분. 시험에서 가짜로 바꿔 끼운다. */
export type EventSourceLike = {
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
  addEventListener(type: string, listener: (event: MessageEvent) => void): void
  close(): void
}

export type LiveConnectionOptions = {
  url?: string
  /** 이벤트 하나가 올 때마다 */
  onEvent: (name: LiveEventName, payload: LivePayload) => void
  /** 연결 상태가 바뀔 때마다. reconnected 는 끊겼다가 다시 이어졌을 때만 true */
  onState?: (state: LiveState, info: { reconnected: boolean }) => void
  /** 연결이 끊기거나 열리지 않았을 때(로그인이 풀렸을 수 있다) */
  onDrop?: () => void
  createSource?: (url: string) => EventSourceLike
}

function parsePayload(raw: unknown): LivePayload {
  if (typeof raw !== 'string') return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    return typeof parsed === 'object' && parsed !== null ? (parsed as LivePayload) : {}
  } catch {
    return {}
  }
}

/**
 * 스트림을 열고, 끊기면 간격을 늘려 가며 다시 잇는다. 돌려받은 함수를 부르면 닫는다.
 * (브라우저의 자동 재연결은 서버가 200 이 아닌 답을 주면 멈추므로 직접 다시 잇는다.)
 */
export function openLiveConnection(options: LiveConnectionOptions): () => void {
  const {
    url = '/api/stream',
    onEvent,
    onState,
    onDrop,
    createSource = (target) => new EventSource(target, { withCredentials: true }),
  } = options

  let source: EventSourceLike | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let attempt = 0
  let everOpened = false
  let closed = false

  const connect = () => {
    if (closed) return
    onState?.('connecting', { reconnected: false })
    const current = createSource(url)
    source = current

    const markOpen = () => {
      if (closed || source !== current) return
      const reconnected = everOpened && attempt > 0
      attempt = 0
      everOpened = true
      onState?.('open', { reconnected })
    }
    current.onopen = markOpen
    current.addEventListener('ready', markOpen)
    for (const name of LIVE_EVENTS) {
      current.addEventListener(name, (event) => {
        if (closed || source !== current) return
        onEvent(name, parsePayload(event.data))
      })
    }
    current.onerror = () => {
      if (closed || source !== current) return
      current.close()
      source = null
      onState?.('connecting', { reconnected: false })
      onDrop?.()
      retryTimer = setTimeout(connect, backoffDelay(attempt))
      attempt += 1
    }
  }

  connect()

  return () => {
    closed = true
    if (retryTimer !== null) clearTimeout(retryTimer)
    source?.close()
    source = null
  }
}
