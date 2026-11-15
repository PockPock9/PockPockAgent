export function createId() {
  return crypto.randomUUID()
}

export async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const field = document.createElement('textarea')
    field.value = text
    field.setAttribute('readonly', '')
    field.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
    document.body.appendChild(field)
    field.select()
    document.execCommand('copy')
    field.remove()
  }
}

export function conversationTitle(text: string, limit = 48) {
  const clean = text.replace(/\s+/g, ' ').trim()
  if (clean.length <= limit) return clean
  const cut = clean.slice(0, limit + 1)
  const boundary = cut.lastIndexOf(' ')
  return `${(boundary > limit * 0.6 ? cut.slice(0, boundary) : clean.slice(0, limit)).replace(/[\s,.;:–-]+$/, '')}…`
}

const CHECK_LINE = /^\s*[-*]?\s*CHECK\s+\d+\s*:\s*(PASS(?:ED)?|COMPLETE[D]?|INCOMPLETE|FAIL(?:ED)?|UNVERIFIED)\s*[-–:]\s*(.+)$/i

export function splitAgentReport(content: string) {
  const checks: Array<{ passed: boolean; text: string }> = []
  const answer = content.split(/\r?\n/).filter((line) => {
    const match = CHECK_LINE.exec(line)
    if (!match) return true
    checks.push({ passed: /^(PASS|COMPLETE)/i.test(match[1]), text: match[2].trim().replace(/^"(.*)"$/, '$1') })
    return false
  }).join('\n').trim()
  if (!answer && checks.length === 1 && checks[0].passed) return { answer: checks[0].text, checks: [] }
  return { answer, checks }
}
