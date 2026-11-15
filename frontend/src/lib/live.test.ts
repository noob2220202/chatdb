import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  backoffDelay,
  createEmitter,
  emitLive,
  openLiveConnection,
  subscribeLive,
  throttle,
  type EventSourceLike,
  type LiveState,
} from './live'

describe('createEmitter', () => {
  it('이름이 같은 이벤트만 듣는 쪽에 전한다', () => {
    const emitter = createEmitter<{ a: number; b: string }>()
    const onA = vi.fn()
    const onB = vi.fn()
    emitter.on('a', onA)
    emitter.on('b', onB)
    emitter.emit('a', 1)
    expect(onA).toHaveBeenCalledWith(1)
    expect(onB).not.toHaveBeenCalled()
  })

  it('그만 듣기를 부르면 더는 받지 않는다', () => {
    const emitter = createEmitter<{ a: number }>()
    const listener = vi.fn()
    const off = emitter.on('a', listener)
    off()
    emitter.emit('a', 1)
    expect(listener).not.toHaveBeenCalled()
  })

  it('듣는 쪽 하나가 실패해도 나머지는 받는다', () => {
    const emitter = createEmitter<{ a: number }>()
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    const second = vi.fn()
    emitter.on('a', () => {
      throw new Error('boom')
    })
    emitter.on('a', second)
    emitter.emit('a', 1)
    expect(second).toHaveBeenCalledWith(1)
    quiet.mockRestore()
  })
})

describe('subscribeLive', () => {
  it('앱 안에 뿌린 이벤트를 받는다', () => {
    const listener = vi.fn()
    const off = subscribeLive('hit', listener)
    emitLive('hit', { id: 1 })
    emitLive('log', { id: 2 })
    off()
    emitLive('hit', { id: 3 })
    expect(listener).toHaveBeenCalledTimes(1)
    expect(listener).toHaveBeenCalledWith({ id: 1 })
  })
})

describe('throttle', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('첫 호출은 바로 나간다', () => {
    const fn = vi.fn()
    const throttled = throttle(fn, 2000)
    throttled()
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('구간 안의 호출은 몇 번이든 끝에 한 번으로 합친다', () => {
    const fn = vi.fn()
    const throttled = throttle(fn, 2000)
    throttled()
    throttled()
    throttled()
    throttled()
    expect(fn).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1999)
    expect(fn).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('2초에 한 번을 넘지 않는다', () => {
    const fn = vi.fn()
    const throttled = throttle(fn, 2000)
    for (let ms = 0; ms < 10_000; ms += 100) {
      throttled()
      vi.advanceTimersByTime(100)
    }
    // 0초에 한 번, 그 뒤 2초마다 한 번씩
    expect(fn.mock.calls.length).toBeLessThanOrEqual(6)
    expect(fn.mock.calls.length).toBeGreaterThanOrEqual(5)
  })

  it('조용해진 뒤의 호출은 다시 바로 나간다', () => {
    const fn = vi.fn()
    const throttled = throttle(fn, 2000)
    throttled()
    vi.advanceTimersByTime(2000)
    throttled()
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('cancel 은 기다리던 호출을 버린다', () => {
    const fn = vi.fn()
    const throttled = throttle(fn, 2000)
    throttled()
    throttled()
    throttled.cancel()
    vi.advanceTimersByTime(5000)
    expect(fn).toHaveBeenCalledTimes(1)
  })
})

describe('backoffDelay', () => {
  it('1초에서 시작해 두 배씩 늘고 30초에서 멈춘다', () => {
    expect([0, 1, 2, 3, 4, 5, 6].map((attempt) => backoffDelay(attempt))).toEqual([
      1000, 2000, 4000, 8000, 16_000, 30_000, 30_000,
    ])
  })
})

class FakeSource implements EventSourceLike {
  static instances: FakeSource[] = []
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  closed = false
  private listeners = new Map<string, ((event: MessageEvent) => void)[]>()

  constructor() {
    FakeSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close() {
    this.closed = true
  }

  send(type: string, data: string) {
    for (const listener of this.listeners.get(type) ?? []) listener({ data } as MessageEvent)
  }
}

describe('openLiveConnection', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeSource.instances = []
  })
  afterEach(() => vi.useRealTimers())

  const last = () => FakeSource.instances[FakeSource.instances.length - 1]!

  it('ready 가 오면 열린 것으로 보고, 이벤트를 JSON 으로 풀어 전한다', () => {
    const onEvent = vi.fn()
    const states: LiveState[] = []
    const close = openLiveConnection({
      onEvent,
      onState: (state) => states.push(state),
      createSource: () => new FakeSource(),
    })
    last().send('ready', '{}')
    last().send('hit', '{"username":"jiwoo_kim92"}')
    expect(states).toEqual(['connecting', 'open'])
    expect(onEvent).toHaveBeenCalledWith('hit', { username: 'jiwoo_kim92' })
    close()
    expect(last().closed).toBe(true)
  })

  it('깨진 본문은 빈 객체로 넘긴다', () => {
    const onEvent = vi.fn()
    openLiveConnection({ onEvent, createSource: () => new FakeSource() })
    last().send('log', 'not json')
    expect(onEvent).toHaveBeenCalledWith('log', {})
  })

  it('끊기면 간격을 늘려 가며 다시 잇고, 다시 이어지면 알려 준다', () => {
    const onDrop = vi.fn()
    const opened: boolean[] = []
    openLiveConnection({
      onEvent: vi.fn(),
      onDrop,
      onState: (state, info) => {
        if (state === 'open') opened.push(info.reconnected)
      },
      createSource: () => new FakeSource(),
    })
    last().send('ready', '{}')
    last().onerror?.(new Event('error'))
    expect(onDrop).toHaveBeenCalledTimes(1)
    expect(FakeSource.instances).toHaveLength(1)

    vi.advanceTimersByTime(1000)
    expect(FakeSource.instances).toHaveLength(2)
    last().onerror?.(new Event('error'))
    vi.advanceTimersByTime(1999)
    expect(FakeSource.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeSource.instances).toHaveLength(3)

    last().send('ready', '{}')
    expect(opened).toEqual([false, true])
  })

  it('닫은 뒤에는 다시 잇지 않는다', () => {
    const close = openLiveConnection({ onEvent: vi.fn(), createSource: () => new FakeSource() })
    last().onerror?.(new Event('error'))
    close()
    vi.advanceTimersByTime(60_000)
    expect(FakeSource.instances).toHaveLength(1)
  })
})
