import { CheckIcon } from '@phosphor-icons/react'
import clsx from 'clsx'
import { DropdownMenu } from 'radix-ui'
import type { ReactElement, ReactNode } from 'react'

import styles from './Menu.module.css'

export type MenuProps = {
  /** 메뉴를 여는 요소(버튼 하나) */
  trigger: ReactElement
  /** MenuItem, MenuCheckItem, MenuRadioGroup, MenuLabel, MenuSeparator */
  children: ReactNode
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  open?: boolean
  onOpenChange?: (open: boolean) => void
  className?: string
}

/** 펼침 메뉴. 떠 있는 종이 면에 먹색 테, 항목 사이는 가는 괘선. 그림자·둥근 모서리 없음. */
export function Menu({
  trigger,
  children,
  align = 'start',
  side = 'bottom',
  open,
  onOpenChange,
  className,
}: MenuProps) {
  return (
    <DropdownMenu.Root open={open} onOpenChange={onOpenChange}>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          className={clsx(styles.content, className)}
          align={align}
          side={side}
          sideOffset={4}
          collisionPadding={8}
        >
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

export type MenuItemProps = {
  children: ReactNode
  onSelect?: () => void
  icon?: ReactNode
  /** 오른쪽 끝의 단축키 글자 */
  shortcut?: string
  /** 오른쪽 끝의 흐린 보조 글 */
  note?: ReactNode
  disabled?: boolean
  className?: string
}

export function MenuItem({
  children,
  onSelect,
  icon,
  shortcut,
  note,
  disabled,
  className,
}: MenuItemProps) {
  return (
    <DropdownMenu.Item
      className={clsx(styles.item, className)}
      onSelect={onSelect}
      disabled={disabled}
    >
      {icon && <span className={styles.icon}>{icon}</span>}
      <span className={styles.text}>{children}</span>
      {note && <span className={styles.note}>{note}</span>}
      {shortcut && <span className={styles.shortcut}>{shortcut}</span>}
    </DropdownMenu.Item>
  )
}

export type MenuCheckItemProps = {
  children: ReactNode
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
}

/** 켜고 끄는 항목. 고른 뒤에도 메뉴가 닫히지 않는다. */
export function MenuCheckItem({
  children,
  checked,
  onCheckedChange,
  disabled,
}: MenuCheckItemProps) {
  return (
    <DropdownMenu.CheckboxItem
      className={clsx(styles.item, styles.checkable)}
      checked={checked}
      onCheckedChange={onCheckedChange}
      onSelect={(event) => event.preventDefault()}
      disabled={disabled}
    >
      <DropdownMenu.ItemIndicator className={styles.check}>
        <CheckIcon size={12} aria-hidden="true" />
      </DropdownMenu.ItemIndicator>
      <span className={styles.text}>{children}</span>
    </DropdownMenu.CheckboxItem>
  )
}

export type MenuRadioGroupProps = {
  value: string
  onValueChange: (value: string) => void
  children: ReactNode
}

export function MenuRadioGroup({ value, onValueChange, children }: MenuRadioGroupProps) {
  return (
    <DropdownMenu.RadioGroup value={value} onValueChange={onValueChange}>
      {children}
    </DropdownMenu.RadioGroup>
  )
}

export type MenuRadioItemProps = {
  value: string
  children: ReactNode
  note?: ReactNode
  disabled?: boolean
}

export function MenuRadioItem({ value, children, note, disabled }: MenuRadioItemProps) {
  return (
    <DropdownMenu.RadioItem
      className={clsx(styles.item, styles.checkable)}
      value={value}
      disabled={disabled}
    >
      <DropdownMenu.ItemIndicator className={styles.check}>
        <CheckIcon size={12} aria-hidden="true" />
      </DropdownMenu.ItemIndicator>
      <span className={styles.text}>{children}</span>
      {note && <span className={styles.note}>{note}</span>}
    </DropdownMenu.RadioItem>
  )
}

/** 항목 묶음의 작은 머리글 */
export function MenuLabel({ children }: { children: ReactNode }) {
  return <DropdownMenu.Label className={styles.label}>{children}</DropdownMenu.Label>
}

/** 묶음 사이의 먹색 줄 */
export function MenuSeparator() {
  return <DropdownMenu.Separator className={styles.separator} />
}
