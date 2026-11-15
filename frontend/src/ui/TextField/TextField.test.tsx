import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { TextField } from './TextField'

afterEach(cleanup)

describe('TextField', () => {
  it('이름과 도움말을 입력 칸에 이어 준다', () => {
    render(<TextField label="그룹 이름" hint="수집함에 이 이름으로 나와요." />)
    const input = screen.getByLabelText('그룹 이름')
    const describedBy = input.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy!)?.textContent).toBe('수집함에 이 이름으로 나와요.')
    expect(input.getAttribute('aria-invalid')).toBeNull()
  })

  it('오류가 있으면 도움말 자리에 오류를 적고 aria-invalid 를 붙인다', () => {
    render(<TextField label="전화번호" hint="나라 번호부터" error="번호가 한 자리 모자라요." />)
    const input = screen.getByLabelText('전화번호')
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByRole('alert').textContent).toBe('번호가 한 자리 모자라요.')
    expect(screen.queryByText('나라 번호부터')).toBeNull()
  })

  it('비밀번호는 "보기"로 드러내고 다시 숨길 수 있다', () => {
    render(<TextField label="비밀번호" type="password" revealable defaultValue="correct horse" />)
    const input = screen.getByLabelText('비밀번호') as HTMLInputElement
    expect(input.type).toBe('password')
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 보기' }))
    expect(input.type).toBe('text')
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 숨기기' }))
    expect(input.type).toBe('password')
  })
})
