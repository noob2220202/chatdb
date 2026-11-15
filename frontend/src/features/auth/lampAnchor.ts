/**
 * object-fit: cover 로 채운 사진 안의 한 점이 화면의 어디에 놓이는지 계산한다.
 * 로그인 화면에서 헤드라인과 사진 속 램프를 잇는 선의 끝점을 구할 때 쓴다.
 */

export type Size = { width: number; height: number }
export type Point = { x: number; y: number }

/** cover 로 채울 때 사진이 그려지는 크기 */
export function coverSize(box: Size, natural: Size): Size {
  const scale = Math.max(box.width / natural.width, box.height / natural.height)
  return { width: natural.width * scale, height: natural.height * scale }
}

/**
 * 사진 안의 점(fraction: 0~1 비율)이 상자 안에서 놓이는 자리(px).
 * position 은 object-position 의 비율(0 = 왼쪽·위, 1 = 오른쪽·아래)이다.
 */
export function coverPoint(
  box: Size,
  natural: Size,
  fraction: Point,
  position: Point = { x: 0, y: 0 },
): Point {
  const drawn = coverSize(box, natural)
  // object-position 의 %는 "남는 길이"에 대한 비율이다. cover 에서는 남는 길이가 0 이하다.
  const offsetX = (box.width - drawn.width) * position.x
  const offsetY = (box.height - drawn.height) * position.y
  return { x: offsetX + fraction.x * drawn.width, y: offsetY + fraction.y * drawn.height }
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value))

/**
 * 램프가 상자 높이의 targetY(0~1) 쯤에 오도록 세로 object-position 을 고른다.
 * 사진이 세로로 넘칠 때만 움직일 수 있고, 가로는 왼쪽(0)에 붙여 둔다.
 * 돌려주는 point 는 그렇게 놓았을 때 램프의 실제 자리다(선은 항상 여기서 끝난다).
 */
export function placeLamp(
  box: Size,
  natural: Size,
  lamp: Point,
  targetY: number,
): { position: Point; point: Point; scale: number } {
  const drawn = coverSize(box, natural)
  const slackY = drawn.height - box.height
  let positionY = 0
  if (slackY > 0.5) {
    const wanted = lamp.y * drawn.height - targetY * box.height
    positionY = clamp01(wanted / slackY)
  }
  const position = { x: 0, y: positionY }
  return {
    position,
    point: coverPoint(box, natural, lamp, position),
    scale: drawn.width / natural.width,
  }
}
