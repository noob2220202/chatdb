import { MagnifyingGlassIcon, XIcon } from '@phosphor-icons/react'
import clsx from 'clsx'
import { forwardRef, useEffect, useImperativeHandle, useRef, type KeyboardEvent } from 'react'

import { Kbd } from '@/ui/Kbd/Kbd'

import styles from './SearchField.module.css'

export type SearchFieldProps = {
  value: string
  onValueChange: (value: string) => void
  placeholder?: string
  /** 읽어 주는 이름. 기본 "찾기" */
  'aria-label'?: string
  /** 어디서든 "/" 를 누르면 이 칸으로 온다. 기본 true. 한 화면에 하나만 켠다 */
  shortcut?: boolean
  /** 밑줄 없이(필터 줄처럼 이미 괘선 안에 있을 때) */
  bare?: boolean
  /** Enter 를 눌렀을 때 */
  onSubmit?: (value: string) => void
  disabled?: boolean
  id?: string
  className?: string
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  )
}

/** 찾기 칸. 돋보기 + 입력 + "/" 키캡. Esc 는 지우고, 비어 있으면 칸에서 나간다. */
export const SearchField = forwardRef<HTMLInputElement, SearchFieldProps>(function SearchField(
  {
    value,
    onValueChange,
    placeholder = '찾기',
    'aria-label': ariaLabel = '찾기',
    shortcut = true,
    bare = false,
    onSubmit,
    disabled = false,
    id,
    className,
  },
  ref,
) {
  const inputRef = useRef<HTMLInputElement>(null)
  useImperativeHandle(ref, () => inputRef.current as HTMLInputElement)

  useEffect(() => {
    if (!shortcut || disabled) return
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return
      if (isTypingTarget(event.target)) return
      // 대화상자가 열려 있으면 그 안의 입력을 방해하지 않는다.
      if (document.querySelector('[role="dialog"], [role="alertdialog"]')) return
      event.preventDefault()
      inputRef.current?.focus()
      inputRef.current?.select()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [shortcut, disabled])

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      if (value) {
        event.preventDefault()
        onValueChange('')
      } else {
        inputRef.current?.blur()
      }
    } else if (event.key === 'Enter') {
      onSubmit?.(value)
    }
  }

  return (
    <div
      className={clsx(styles.search, bare && styles.bare, className)}
      data-disabled={disabled || undefined}
      role="search"
    >
      <MagnifyingGlassIcon className={styles.glass} aria-hidden="true" />
      <input
        ref={inputRef}
        id={id}
        type="text"
        inputMode="search"
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
        className={styles.input}
        value={value}
        placeholder={placeholder}
        aria-label={ariaLabel}
        aria-keyshortcuts={shortcut ? '/' : undefined}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {value ? (
        <button
          type="button"
          className={styles.clear}
          aria-label="찾는 말 지우기"
          onClick={() => {
            onValueChange('')
            inputRef.current?.focus()
          }}
        >
          <XIcon size={13} aria-hidden="true" />
        </button>
      ) : (
        shortcut && !disabled && <Kbd className={styles.key}>/</Kbd>
      )}
    </div>
  )
})
