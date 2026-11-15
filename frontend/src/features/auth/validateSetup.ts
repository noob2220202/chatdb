export const MIN_PASSWORD_LENGTH = 8

export type SetupErrors = {
  password?: string
  confirm?: string
  form?: string
  alreadySetup?: boolean
}

/** 처음 설정의 두 칸을 확인한다. 문제가 없으면 빈 객체. */
export function validateSetup(password: string, confirm: string): SetupErrors {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return {
      password: `${MIN_PASSWORD_LENGTH}자 이상으로 정해 주세요. 지금은 ${password.length}자예요.`,
    }
  }
  if (password !== confirm) return { confirm: '위와 똑같이 적어 주세요.' }
  return {}
}
