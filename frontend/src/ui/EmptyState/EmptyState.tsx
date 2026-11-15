import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { Photo } from '@/assets/photos'

import styles from './EmptyState.module.css'

/** 아직 아무것도 적히지 않은 양식. 사진이 어울리지 않는 자리에 쓴다. */
export function BlankForm({ className }: { className?: string }) {
  return (
    <svg
      className={clsx(styles.form, className)}
      width="132"
      height="96"
      viewBox="0 0 132 96"
      aria-hidden="true"
      focusable="false"
    >
      {/* 종이 */}
      <rect x="0.5" y="0.5" width="131" height="95" className={styles.formSheet} />
      {/* 머리 칸 */}
      <path d="M0 20.5H132" className={styles.formInk} />
      <path d="M10 10.5H46" className={styles.formBar} />
      {/* 꺼진 램프 */}
      <circle cx="119" cy="10.5" r="3.5" className={styles.formLamp} />
      {/* 괘선: 아직 한 줄도 적지 않았다 */}
      <path d="M0 35.5H132M0 50.5H132M0 65.5H132M0 80.5H132" className={styles.formRule} />
      {/* 세로 칸 */}
      <path d="M34.5 20V96M98.5 20V96" className={styles.formRule} />
    </svg>
  )
}

export interface EmptyStateProps {
  /** 무엇이 없는지 제품의 말투로 한 줄 (명조): "아직 받아 적은 사람이 없어요" */
  title: ReactNode
  /** 어떻게 하면 생기는지 한 문장 */
  description?: ReactNode
  /** 동작 하나 (버튼) */
  action?: ReactNode
  /** 사진 (assets/photos). 없으면 빈 양식 그림을 쓴다 */
  photo?: Photo
  /**
   * page    화면 한 장을 채우는 빈 상태: 큰 사진 + 글
   * section 꼭지 안의 빈 상태: 작은 그림 + 글 (기본)
   * inline  표나 목록 안의 빈 상태: 글만
   */
  size?: 'page' | 'section' | 'inline'
  /** 제목 요소. 기본 h3 */
  as?: 'h2' | 'h3' | 'h4' | 'p'
  className?: string
}

/** 빈 상태: 무엇이 없는지 말하고, 한 문장으로 돕고, 동작 하나를 내민다. */
export function EmptyState({
  title,
  description,
  action,
  photo,
  size = 'section',
  as: Heading = 'h3',
  className,
}: EmptyStateProps) {
  return (
    <div className={clsx(styles.empty, styles[size], className)}>
      {size !== 'inline' &&
        (photo ? (
          <figure className={styles.plate}>
            <img
              src={photo.src}
              srcSet={photo.srcSet}
              width={photo.width}
              height={photo.height}
              alt={photo.alt}
              loading="lazy"
              decoding="async"
              style={{ objectPosition: photo.focus }}
            />
            <figcaption>
              <b>{photo.title}.</b> {photo.caption}. {photo.credit}
            </figcaption>
          </figure>
        ) : (
          <BlankForm className={styles.art} />
        ))}
      <div className={styles.body}>
        <Heading className={styles.title}>{title}</Heading>
        {description && <p className={styles.description}>{description}</p>}
        {action && <div className={styles.action}>{action}</div>}
      </div>
    </div>
  )
}
