import operatorUrl from './assets/operator-1941.jpg'

/**
 * 로그인 화면의 사진과, 그 안에서 불이 켜지는 램프의 자리.
 * 램프 자리는 사진 크기에 대한 비율로 적는다(사진을 같은 크롭으로 바꿔 끼워도 그대로 맞는다).
 */
export const OPERATOR_PHOTO = {
  src: operatorUrl,
  alt: '교환대 앞에 앉은 교환원이 수많은 램프 가운데 하나를 손끝으로 가리키고 있는 흑백 사진',
  /** 원본 크기(px) */
  size: { width: 1866, height: 1800 },
  /** 램프 중심: 왼쪽·위에서부터의 비율 */
  lamp: { x: 0.2287, y: 0.41884 },
  /** 램프의 반지름: 사진 폭에 대한 비율(가로, 세로) */
  lampRadius: { x: 0.0054, y: 0.0062 },
  caption: '불 켜진 회선을 찾는 교환원',
  credit: '메릴랜드 애버딘, 1941년 · 사진 존 바숀 · 미국 의회도서관 소장',
} as const
