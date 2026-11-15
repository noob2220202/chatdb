import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  SelectionAction,
  SelectionBand,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  useRowNavigation,
} from './Table'

afterEach(cleanup)

function Rows({ onToggle }: { onToggle: (index: number) => void }) {
  const nav = useRowNavigation({ count: 3, onToggle })
  return (
    <Table columns={[100, null]} aria-label="견본">
      <THead>
        <TR>
          <TH>유저</TH>
          <TH sort="desc" onSort={() => undefined}>
            마지막 감지
          </TH>
        </TR>
      </THead>
      <TBody>
        {['가', '나', '다'].map((name, index) => (
          <TR key={name} {...nav.getRowProps(index)}>
            <TD>{name}</TD>
            <TD>방금</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  )
}

describe('Table', () => {
  it('열 폭을 colgroup 으로 넘긴다', () => {
    const { container } = render(<Rows onToggle={() => undefined} />)
    const cols = container.querySelectorAll('col')
    expect(cols).toHaveLength(2)
    expect((cols[0] as HTMLElement).style.width).toBe('100px')
    expect((cols[1] as HTMLElement).style.width).toBe('')
  })

  it('정렬한 열에 aria-sort 를 붙인다', () => {
    const { getAllByRole } = render(<Rows onToggle={() => undefined} />)
    const headers = getAllByRole('columnheader')
    expect(headers[0]?.getAttribute('aria-sort')).toBeNull()
    expect(headers[1]?.getAttribute('aria-sort')).toBe('descending')
  })

  it('선택한 행에 aria-selected 를 붙인다', () => {
    const { getAllByRole } = render(
      <Table>
        <TBody>
          <TR selected>
            <TD>가</TD>
          </TR>
          <TR selected={false}>
            <TD>나</TD>
          </TR>
          <TR>
            <TD>다</TD>
          </TR>
        </TBody>
      </Table>,
    )
    const rows = getAllByRole('row')
    expect(rows.map((row) => row.getAttribute('aria-selected'))).toEqual(['true', 'false', null])
  })
})

describe('useRowNavigation', () => {
  it('Tab 으로는 한 행에만 멈추고, 화살표로 옮긴다', () => {
    const onToggle = vi.fn()
    const { container } = render(<Rows onToggle={onToggle} />)
    const rows = Array.from(container.querySelectorAll<HTMLTableRowElement>('tbody tr'))
    expect(rows.map((row) => row.tabIndex)).toEqual([0, -1, -1])

    rows[0]?.focus()
    fireEvent.keyDown(rows[0]!, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(rows[1])
    expect(rows.map((row) => row.tabIndex)).toEqual([-1, 0, -1])

    fireEvent.keyDown(rows[1]!, { key: 'End' })
    expect(document.activeElement).toBe(rows[2])
    fireEvent.keyDown(rows[2]!, { key: 'ArrowDown' }) // 끝에서는 더 내려가지 않는다
    expect(document.activeElement).toBe(rows[2])
    fireEvent.keyDown(rows[2]!, { key: 'Home' })
    expect(document.activeElement).toBe(rows[0])
  })

  it('Space 로 고른다', () => {
    const onToggle = vi.fn()
    const { container } = render(<Rows onToggle={onToggle} />)
    const rows = Array.from(container.querySelectorAll<HTMLTableRowElement>('tbody tr'))
    fireEvent.keyDown(rows[1]!, { key: ' ' })
    expect(onToggle).toHaveBeenCalledWith(1)
  })
})

describe('SelectionBand', () => {
  it('아무것도 고르지 않으면 띠가 없다', () => {
    const { container } = render(<SelectionBand count={0} onClear={() => undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('고른 수와 동작을 보여 준다', () => {
    const { getByRole } = render(
      <SelectionBand count={1234} onClear={() => undefined} label="선택한 유저에게 할 일">
        <SelectionAction>@아이디 복사</SelectionAction>
      </SelectionBand>,
    )
    const band = getByRole('toolbar')
    expect(band.getAttribute('aria-label')).toBe('선택한 유저에게 할 일')
    expect(getByRole('status').textContent).toBe('1,234명 선택됨')
    expect(getByRole('button', { name: '@아이디 복사' })).not.toBeNull()
  })

  it('Esc 로 선택을 푼다. 입력 칸에서 누른 Esc 는 건드리지 않는다', () => {
    const onClear = vi.fn()
    const { container } = render(
      <div>
        <input aria-label="찾기" />
        <SelectionBand count={2} onClear={onClear} />
      </div>,
    )
    fireEvent.keyDown(container.querySelector('input')!, { key: 'Escape' })
    expect(onClear).not.toHaveBeenCalled()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(onClear).toHaveBeenCalledTimes(1)
  })

  it('선택 해제 버튼', () => {
    const onClear = vi.fn()
    const { getByRole } = render(<SelectionBand count={2} onClear={onClear} />)
    fireEvent.click(getByRole('button', { name: /선택 해제/ }))
    expect(onClear).toHaveBeenCalledTimes(1)
  })
})
