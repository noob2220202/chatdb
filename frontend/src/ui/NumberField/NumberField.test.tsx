import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { clampNumber, NumberField, parseNumber } from './NumberField'

afterEach(cleanup)

describe('clampNumber', () => {
  it('범위 밖의 값을 가장 가까운 끝으로 옮긴다', () => {
    expect(clampNumber(25, 1, 20)).toBe(20)
    expect(clampNumber(0, 1, 20)).toBe(1)
    expect(clampNumber(7, 1, 20)).toBe(7)
    expect(clampNumber(7)).toBe(7)
  })
})

describe('parseNumber', () => {
  it('쉼표와 빈칸을 걷어 내고 읽는다', () => {
    expect(parseNumber('4,812')).toBe(4812)
    expect(parseNumber(' 20 ')).toBe(20)
  })

  it('숫자가 아니면 null 이다', () => {
    expect(parseNumber('')).toBeNull()
    expect(parseNumber('-')).toBeNull()
    expect(parseNumber('1.2.3')).toBeNull()
  })
})

function Harness({ initial }: { initial: number | null }) {
  const [value, setValue] = useState<number | null>(initial)
  return (
    <>
      <NumberField
        label="계정마다 들어갈 그룹"
        value={value}
        onValueChange={setValue}
        min={1}
        max={20}
        unit="곳"
      />
      <output>{value === null ? '빔' : value}</output>
    </>
  )
}

describe('NumberField', () => {
  it('위·아래 화살표로 한 칸씩 바꾸고 범위를 넘지 않는다', () => {
    render(<Harness initial={19} />)
    const input = screen.getByRole('spinbutton', { name: '계정마다 들어갈 그룹' })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(screen.getByRole('status').textContent).toBe('20')
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(screen.getByRole('status').textContent).toBe('19')
  })

  it('쓰는 동안에는 그대로 두고, 칸을 떠날 때 범위에 맞춘다', () => {
    render(<Harness initial={5} />)
    const input = screen.getByRole('spinbutton') as HTMLInputElement
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: '45' } })
    expect(input.value).toBe('45')
    // 범위 밖의 값은 아직 알리지 않는다
    expect(screen.getByRole('status').textContent).toBe('5')
    fireEvent.blur(input)
    expect(screen.getByRole('status').textContent).toBe('20')
    expect(input.value).toBe('20')
  })

  it('끝에 닿으면 그쪽 버튼을 못 쓰게 한다', () => {
    render(<Harness initial={20} />)
    expect((screen.getByRole('button', { name: '늘리기' }) as HTMLButtonElement).disabled).toBe(
      true,
    )
    expect((screen.getByRole('button', { name: '줄이기' }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  })
})
