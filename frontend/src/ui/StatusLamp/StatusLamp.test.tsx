import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import {
  ACCOUNT_STATUS,
  AccountStatusLabel,
  GROUP_STATUS,
  GroupStatusLabel,
  LEAD_STATUS,
  LeadStatusLabel,
  StatusLamp,
} from './StatusLamp'

afterEach(cleanup)

describe('상태값 → 램프와 글자', () => {
  it('수집한 유저', () => {
    expect(LEAD_STATUS).toEqual({
      new: { kind: 'lit', label: '새로 수집됨' },
      reviewed: { kind: 'off', label: '확인함' },
      contacted: { kind: 'done', label: '연락함' },
      excluded: { kind: 'muted', label: '제외' },
    })
  })

  it('계정', () => {
    expect(
      Object.fromEntries(Object.entries(ACCOUNT_STATUS).map(([k, v]) => [k, v.label])),
    ).toEqual({
      connecting: '연결하는 중',
      active: '정상',
      flood_wait: '잠시 대기',
      reauth_required: '다시 로그인 필요',
      banned: '계정 정지됨',
      error: '연결 끊김',
      offline: '꺼 둠',
    })
  })

  it('그룹', () => {
    expect(Object.fromEntries(Object.entries(GROUP_STATUS).map(([k, v]) => [k, v.label]))).toEqual({
      queued: '가입 대기',
      joining: '가입하는 중',
      requested: '승인 기다리는 중',
      joined: '가입됨',
      failed: '가입 실패',
      left: '나간 그룹',
    })
  })

  it('빨강(lit)은 새로 수집됨에만 쓴다', () => {
    const lit = [
      ...Object.values(LEAD_STATUS),
      ...Object.values(ACCOUNT_STATUS),
      ...Object.values(GROUP_STATUS),
    ].filter((meaning) => meaning.kind === 'lit')
    expect(lit).toEqual([{ kind: 'lit', label: '새로 수집됨' }])
  })

  it('문제 상태는 모두 반전(problem)으로 드러낸다', () => {
    expect(ACCOUNT_STATUS.reauth_required.kind).toBe('problem')
    expect(ACCOUNT_STATUS.banned.kind).toBe('problem')
    expect(ACCOUNT_STATUS.error.kind).toBe('problem')
    expect(GROUP_STATUS.failed.kind).toBe('problem')
  })
})

describe('StatusLabel', () => {
  it('글자를 함께 보여 준다', () => {
    const { container } = render(<LeadStatusLabel status="new" />)
    expect(container.textContent).toBe('새로 수집됨')
  })

  it('문구를 바꿔 쓸 수 있다', () => {
    const { container } = render(
      <AccountStatusLabel status="flood_wait">14분 뒤 다시 시작</AccountStatusLabel>,
    )
    expect(container.textContent).toBe('14분 뒤 다시 시작')
  })

  it('그룹 상태', () => {
    const { container } = render(<GroupStatusLabel status="requested" />)
    expect(container.textContent).toBe('승인 기다리는 중')
  })
})

describe('StatusLamp', () => {
  it('옆에 글자가 있으면 장식으로 본다', () => {
    const { container } = render(<StatusLamp kind="ok" />)
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
  })

  it('혼자 쓰일 때는 이름을 준다', () => {
    const { getByRole } = render(<StatusLamp kind="lit" label="확인이 필요한 계정 1개" />)
    expect(getByRole('img').getAttribute('aria-label')).toBe('확인이 필요한 계정 1개')
  })
})
