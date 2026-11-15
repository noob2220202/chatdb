import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { SearchField } from './SearchField'

afterEach(cleanup)

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <SearchField value={value} onValueChange={setValue} />
      <textarea aria-label="메모" />
    </>
  )
}

describe('SearchField', () => {
  it('어디서든 "/" 를 누르면 찾기 칸으로 온다', () => {
    render(<Harness />)
    const input = screen.getByRole('textbox', { name: '찾기' })
    expect(document.activeElement).not.toBe(input)
    fireEvent.keyDown(document.body, { key: '/' })
    expect(document.activeElement).toBe(input)
  })

  it('다른 칸에 쓰는 중이면 "/" 를 가로채지 않는다', () => {
    render(<Harness />)
    const memo = screen.getByRole('textbox', { name: '메모' })
    memo.focus()
    fireEvent.keyDown(memo, { key: '/' })
    expect(document.activeElement).toBe(memo)
  })

  it('Esc 는 적은 말을 지운다', () => {
    render(<Harness initial="견적" />)
    const input = screen.getByRole('textbox', { name: '찾기' }) as HTMLInputElement
    input.focus()
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(input.value).toBe('')
  })

  it('값이 있으면 지우기 버튼이 나온다', () => {
    render(<Harness initial="견적" />)
    fireEvent.click(screen.getByRole('button', { name: '찾는 말 지우기' }))
    expect((screen.getByRole('textbox', { name: '찾기' }) as HTMLInputElement).value).toBe('')
  })
})
