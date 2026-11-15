/**
 * 견본 화면 전용. :hover / :active / :focus-visible / :focus-within 규칙을 복제해서
 * data-force="hover" 같은 속성으로도 같은 모습이 나오게 한다(멈춘 화면에서 상태를 나란히 보여 주려고).
 *
 *   <Button data-force="hover">   → 올려놓은 모습
 *   <div data-force-within="focus-within"><TextField/></div>   → 안쪽 틀이 "쓰는 중" 모습
 *
 * 실제 제품 화면에서는 쓰지 않는다.
 */
const PSEUDO = /:(hover|active|focus-visible|focus-within)/g

function forcedSelector(selector: string): string[] {
  if (selector.includes('data-force')) return []
  const direct = selector.replace(PSEUDO, (_, name: string) => `[data-force~="${name}"]`)
  const forced = [direct]
  // focus-within 은 감싼 요소에서 내려 줄 수도 있게 한다.
  if (selector.includes(':focus-within')) {
    forced.push(`[data-force-within~="focus-within"] ${selector.replace(/:focus-within/g, '')}`)
  }
  return forced
}

function visit(container: CSSStyleSheet | CSSGroupingRule): void {
  const rules = container.cssRules
  for (let index = rules.length - 1; index >= 0; index -= 1) {
    const rule = rules[index]
    if (rule instanceof CSSStyleRule) {
      if (!PSEUDO.test(rule.selectorText)) continue
      PSEUDO.lastIndex = 0
      const selectors = rule.selectorText
        .split(',')
        .flatMap((selector) => forcedSelector(selector.trim()))
      if (selectors.length === 0) continue
      try {
        container.insertRule(`${selectors.join(', ')} { ${rule.style.cssText} }`, index + 1)
      } catch {
        // 복제할 수 없는 선택자는 건너뛴다.
      }
    } else if (rule instanceof CSSMediaRule || rule instanceof CSSSupportsRule) {
      visit(rule)
    }
  }
}

const seen = new WeakSet<CSSStyleSheet>()

export function forcePseudoStates(): void {
  for (const sheet of Array.from(document.styleSheets)) {
    if (seen.has(sheet)) continue
    try {
      visit(sheet)
      seen.add(sheet)
    } catch {
      // 다른 출처의 스타일시트는 읽을 수 없다.
    }
  }
}
