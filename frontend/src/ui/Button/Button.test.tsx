import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Button } from './Button'

afterEach(cleanup)

describe('Button', () => {
  it('기본은 type="button" 이라 폼을 실수로 보내지 않는다', () => {
    render(<Button>내보내기</Button>)
    expect(screen.getByRole('button', { name: '내보내기' }).getAttribute('type')).toBe('button')
  })

  it('처리 중에는 누를 수 없고, 읽어 주는 프로그램에 알린다', () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        로그인
      </Button>,
    )
    const button = screen.getByRole('button')
    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
    expect(button.getAttribute('aria-busy')).toBe('true')
    expect(button.textContent).toContain('처리하고 있어요')
    // 폭을 지키려고 원래 글자는 그대로 둔다
    expect(button.textContent).toContain('로그인')
  })

  it('asChild 는 자식 요소에 버튼 모양을 입힌다', () => {
    render(
      <Button asChild variant="solid" trailingIcon={<i data-testid="icon" />}>
        <a href="/leads">수집함 보기</a>
      </Button>,
    )
    const link = screen.getByRole('link', { name: '수집함 보기' })
    expect(link.getAttribute('href')).toBe('/leads')
    expect(link.className).not.toBe('')
    expect(link.contains(screen.getByTestId('icon'))).toBe(true)
  })
})
