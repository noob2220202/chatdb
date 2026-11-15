import { describe, expect, it } from 'vitest'

import { summarizeShell, type ShellOverview } from './overview'

const overview: ShellOverview = {
  today_new: 128,
  accounts_connected: 9,
  accounts_total: 10,
  groups_monitoring: 187,
  join_requests_pending: 6,
  accounts: [
    { id: 1, display_name: '지우', status: 'active' },
    { id: 7, display_name: '예린', status: 'flood_wait' },
    { id: 10, display_name: '건우', status: 'reauth_required' },
  ],
  recent_hits: [{ created_at: '2026-11-15T05:13:00Z' }, { created_at: '2026-11-15T05:14:00Z' }],
}

describe('summarizeShell', () => {
  it('연결되어 있고 계정이 붙어 있을 때만 받는 중이다', () => {
    expect(summarizeShell(overview, 'open').receiving).toBe(true)
    expect(summarizeShell(overview, 'connecting').receiving).toBe(false)
    expect(summarizeShell({ ...overview, accounts_connected: 0 }, 'open').receiving).toBe(false)
    expect(summarizeShell(undefined, 'open').receiving).toBe(false)
  })

  it('손봐야 하는 계정만 센다(잠시 대기는 저절로 풀린다)', () => {
    expect(summarizeShell(overview, 'open').attention).toBe(1)
  })

  it('가장 늦은 감지 시각을 고른다', () => {
    expect(summarizeShell(overview, 'open').lastHitAt).toBe('2026-11-15T05:14:00Z')
    expect(summarizeShell({ ...overview, recent_hits: [] }, 'open').lastHitAt).toBeNull()
  })
})
