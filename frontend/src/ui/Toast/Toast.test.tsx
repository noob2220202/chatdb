import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ToastProvider, useToast } from './Toast'

afterEach(cleanup)

function Trigger({ onUndo }: { onUndo: () => void }) {
  const toast = useToast()
  return (
    <>
      <button onClick={() => toast.show('3명의 @아이디를 복사했어요')}>보통</button>
      <button
        onClick={() =>
          toast.problem('내보내지 못했어요.', { action: { label: '다시 시도', onClick: onUndo } })
        }
      >
        문제
      </button>
      <button onClick={() => toast.dismiss()}>모두 닫기</button>
    </>
  )
}

describe('Toast', () => {
  it('useToast 로 알림 띠를 띄운다', () => {
    render(
      <ToastProvider>
        <Trigger onUndo={() => {}} />
      </ToastProvider>,
    )
    fireEvent.click(screen.getByText('보통'))
    expect(screen.getByText('3명의 @아이디를 복사했어요')).toBeTruthy()
  })

  it('문제 알림의 동작 버튼을 누르면 그 일을 한다', () => {
    const onUndo = vi.fn()
    render(
      <ToastProvider>
        <Trigger onUndo={onUndo} />
      </ToastProvider>,
    )
    fireEvent.click(screen.getByText('문제'))
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(onUndo).toHaveBeenCalledTimes(1)
  })

  it('한꺼번에 세 개까지만 쌓인다', () => {
    render(
      <ToastProvider>
        <Trigger onUndo={() => {}} />
      </ToastProvider>,
    )
    act(() => {
      for (let count = 0; count < 5; count += 1) fireEvent.click(screen.getByText('보통'))
    })
    expect(screen.getAllByText('3명의 @아이디를 복사했어요')).toHaveLength(3)
  })

  it('공급자 밖에서 쓰면 바로 알려 준다', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Trigger onUndo={() => {}} />)).toThrow(/ToastProvider/)
    quiet.mockRestore()
  })
})
