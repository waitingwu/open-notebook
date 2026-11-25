export function formatTokens(n: number | null | undefined): string {
  const v = n ?? 0
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`
  return String(v)
}

export function formatUsd(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n > 0 && n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(2)}`
}

export function formatMs(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n}ms`
}

export function formatDateTime(iso: string | null | undefined, locale: string): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(locale)
  } catch {
    return iso
  }
}

export const PROVIDER_LABELS: Record<string, string> = {
  claude_code: 'Claude Code',
  codex_cli: 'Codex',
}

export function providerLabel(p: string): string {
  return PROVIDER_LABELS[p] ?? p
}

// Explicit key tables (instead of template strings) so every translation key
// stays greppable and the unused-key test can see it.
const FEATURE_KEYS: Record<string, string> = {
  chat: 'aiAudit.features.chat',
  source_chat: 'aiAudit.features.source_chat',
  notebook_chat: 'aiAudit.features.notebook_chat',
  ask: 'aiAudit.features.ask',
  tools: 'aiAudit.features.tools',
  transformation: 'aiAudit.features.transformation',
  large_context: 'aiAudit.features.large_context',
}
const FAILURE_KEYS: Record<string, string> = {
  cli_missing: 'aiAudit.failures.cli_missing',
  not_logged_in: 'aiAudit.failures.not_logged_in',
  rate_limited: 'aiAudit.failures.rate_limited',
  timeout: 'aiAudit.failures.timeout',
  cli_error: 'aiAudit.failures.cli_error',
  parse_error: 'aiAudit.failures.parse_error',
  empty_response: 'aiAudit.failures.empty_response',
  cancelled: 'aiAudit.failures.cancelled',
}
const LIMIT_STATUS_KEYS: Record<string, string> = {
  allowed: 'aiAudit.limits.status.allowed',
  allowed_warning: 'aiAudit.limits.status.allowed_warning',
  rejected: 'aiAudit.limits.status.rejected',
}
const WINDOW_KEYS: Record<string, string> = {
  five_hour: 'aiAudit.limits.windows.five_hour',
  seven_day: 'aiAudit.limits.windows.seven_day',
  individual: 'aiAudit.limits.windows.individual',
}

type T = (key: string) => string

function lookup(table: Record<string, string>, t: T, value: string | null | undefined): string {
  if (!value) return '—'
  const key = table[value]
  return key ? t(key) : value
}

export const featureLabel = (t: T, v: string | null | undefined) => lookup(FEATURE_KEYS, t, v)
export const failureLabel = (t: T, v: string | null | undefined) => lookup(FAILURE_KEYS, t, v)
export const limitStatusLabel = (t: T, v: string | null | undefined) => lookup(LIMIT_STATUS_KEYS, t, v)
export const windowLabel = (t: T, v: string | null | undefined) => lookup(WINDOW_KEYS, t, v)
