import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Pagination } from './Pagination'

afterEach(cleanup)

describe('Pagination', () => {
  it('어디쯤 보고 있는지 말한다', () => {
    const { container } = render(
      <Pagination
        page={1}
        pageSize={50}
        total={4812}
        onPageChange={() => undefined}
        sortLabel="마지막 감지가 가까운 순서"
      />,
    )
    expect(container.querySelector('p')?.textContent).toBe(
      '4,812명 가운데 1–50번째 · 마지막 감지가 가까운 순서',
    )
  })

  it('마지막 쪽은 남은 만큼만 센다', () => {
    const { container } = render(
      <Pagination page={97} pageSize={50} total={4812} onPageChange={() => undefined} />,
    )
    expect(container.querySelector('p')?.textContent).toBe('4,812명 가운데 4,801–4,812번째')
  })

  it('첫 쪽에서는 이전을, 마지막 쪽에서는 다음을 누를 수 없다', () => {
    const first = render(
      <Pagination page={1} pageSize={50} total={120} onPageChange={() => undefined} />,
    )
    expect((first.getByRole('button', { name: '이전' }) as HTMLButtonElement).disabled).toBe(true)
    expect((first.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(false)
    cleanup()
    const last = render(
      <Pagination page={3} pageSize={50} total={120} onPageChange={() => undefined} />,
    )
    expect((last.getByRole('button', { name: '이전' }) as HTMLButtonElement).disabled).toBe(false)
    expect((last.getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('쪽을 넘기면 알려 준다', () => {
    const onPageChange = vi.fn()
    const { getByRole } = render(
      <Pagination page={2} pageSize={50} total={4812} onPageChange={onPageChange} />,
    )
    fireEvent.click(getByRole('button', { name: '다음' }))
    fireEvent.click(getByRole('button', { name: '이전' }))
    expect(onPageChange.mock.calls).toEqual([[3], [1]])
  })

  it('한 쪽 크기를 바꿀 수 있다', () => {
    const onPageSizeChange = vi.fn()
    const { getByRole } = render(
      <Pagination
        page={1}
        pageSize={50}
        total={4812}
        onPageChange={() => undefined}
        onPageSizeChange={onPageSizeChange}
      />,
    )
    expect(getByRole('button', { name: '50명씩' }).getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(getByRole('button', { name: '100명씩' }))
    fireEvent.click(getByRole('button', { name: '50명씩' })) // 이미 고른 크기는 다시 알리지 않는다
    expect(onPageSizeChange.mock.calls).toEqual([[100]])
  })

  it('아무것도 없을 때', () => {
    const { container, getByRole } = render(
      <Pagination page={1} pageSize={50} total={0} onPageChange={() => undefined} />,
    )
    expect(container.querySelector('p')?.textContent).toBe('보여 줄 항목이 없어요')
    expect((getByRole('button', { name: '다음' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
