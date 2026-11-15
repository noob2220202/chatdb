import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import type { ShellOverview } from '../overview'
import { summarizeShell } from '../overview'
import { lastHitSentence, StatusLine } from './StatusLine'

afterEach(cleanup)

const now = new Date(2026, 10, 15, 14, 17)

const overview: ShellOverview = {
  today_new: 128,
  accounts_connected: 9,
  accounts_total: 10,
  groups_monitoring: 187,
  join_requests_pending: 0,
  accounts: [
    { id: 1, display_name: '지우', status: 'active' },
    { id: 10, display_name: '건우', status: 'reauth_required' },
  ],
  recent_hits: [{ created_at: new Date(2026, 10, 15, 14, 14).toISOString() }],
}

describe('lastHitSentence', () => {
  it('오늘이면 시각만 적는다', () => {
    expect(lastHitSentence(new Date(2026, 10, 15, 14, 14).toISOString(), now)).toBe(
      '오후 2:14에 마지막으로 받아 적었어요',
    )
  })

  it('어제면 "어제"를 붙인다', () => {
    expect(lastHitSentence(new Date(2026, 10, 14, 23, 2).toISOString(), now)).toBe(
      '어제 오후 11:02에 마지막으로 받아 적었어요',
    )
  })

  it('받아 적은 게 없으면 그렇게 말한다', () => {
    expect(lastHitSentence(null, now)).toBe('아직 받아 적은 게 없어요')
  })
})

describe('StatusLine', () => {
  const renderLine = (props: Partial<Parameters<typeof StatusLine>[0]> = {}) =>
    render(
      <MemoryRouter>
        <StatusLine
          overview={overview}
          failed={false}
          summary={summarizeShell(overview, 'open')}
          live="open"
          onRetry={() => {}}
          now={now}
          {...props}
        />
      </MemoryRouter>,
    )

  it('날짜와 받는 상태를 글자로 적는다', () => {
    renderLine()
    expect(screen.getByText('2026년 11월 15일 일요일')).toBeTruthy()
    const status = screen.getByRole('status').textContent
    expect(status).toContain('받는 중')
    expect(status).toContain('계정 9/10')
    expect(status).toContain('그룹 187곳')
    expect(status).toContain('오후 2:14에 마지막으로 받아 적었어요')
  })

  it('확인이 필요한 계정이 있으면 말로 알리고 계정 화면으로 잇는다', () => {
    renderLine()
    const link = screen.getByRole('link', { name: '계정 1개를 확인해 주세요' })
    expect(link.getAttribute('href')).toBe('/accounts')
  })

  it('연결이 끊겨 있으면 받는 중이라고 하지 않는다', () => {
    renderLine({ summary: summarizeShell(overview, 'connecting'), live: 'connecting' })
    expect(screen.getByRole('status').textContent).toContain('다시 잇는 중')
  })

  it('불러오지 못해도 줄은 남고, 조용히 알린다', () => {
    renderLine({ overview: undefined, failed: true, summary: summarizeShell(undefined, 'open') })
    expect(screen.getByRole('status').textContent).toContain('상태를 불러오지 못했어요')
    expect(screen.getByRole('button', { name: '다시 불러오기' })).toBeTruthy()
  })
})
