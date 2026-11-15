import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'

import type { Photo } from '@/assets/photos'

import styles from './Figure.module.css'

export interface FigureProps {
  /** assets/photos 목록의 사진 */
  photo: Photo
  /** 보여 줄 높이(px). 주면 이 높이에 맞춰 잘라서 보여 준다 */
  height?: number
  /** 가로세로 비 (예: "4 / 3"). height 대신 쓴다. 둘 다 없으면 사진의 원래 비율 */
  ratio?: string
  /**
   * 캡션.
   *   full   굵은 첫 구절 + 어디서·언제 + 찍은 사람 (기본)
   *   credit 찍은 사람만
   *   none   없음 (사진이 순전히 분위기일 때. 대체 글은 그대로 읽힌다)
   */
  caption?: 'full' | 'credit' | 'none'
  /** 캡션 끝에 덧붙이는 말 */
  note?: ReactNode
  /** 화면에 들어오자마자 보이는 사진이면 true (먼저 내려받는다) */
  priority?: boolean
  /** 사진이 순전히 장식일 때 true (대체 글을 읽지 않는다) */
  decorative?: boolean
  className?: string
}

/** 사진 + 캡션. 사진은 먹/종이 듀오톤으로 맞춘 것만 쓴다 (assets/photos). */
export function Figure({
  photo,
  height,
  ratio,
  caption = 'full',
  note,
  priority = false,
  decorative = false,
  className,
}: FigureProps) {
  const cropped = height !== undefined || ratio !== undefined
  const style: CSSProperties = {
    objectPosition: photo.focus,
    ...(height !== undefined ? { height } : null),
    ...(ratio !== undefined ? { aspectRatio: ratio } : null),
  }
  return (
    <figure className={clsx(styles.figure, className)}>
      <img
        className={clsx(styles.image, cropped && styles.cropped)}
        src={photo.src}
        srcSet={photo.srcSet}
        width={photo.width}
        height={photo.height}
        alt={decorative ? '' : photo.alt}
        loading={priority ? 'eager' : 'lazy'}
        decoding="async"
        style={style}
      />
      {caption !== 'none' && (
        <figcaption className={styles.caption}>
          {caption === 'full' && (
            <>
              <b>{photo.title}.</b> {photo.caption}.{' '}
            </>
          )}
          {photo.credit}
          {note && <> · {note}</>}
        </figcaption>
      )}
    </figure>
  )
}
