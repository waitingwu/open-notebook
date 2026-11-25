'use client'

import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useAuditRun, useAuditRuns } from '@/lib/hooks/use-audit'
import { useTranslation } from '@/lib/hooks/use-translation'
import { formatDateTime, formatMs, formatTokens, formatUsd, providerLabel, featureLabel, failureLabel } from './format'

const PAGE = 25
const ALL = '__all__'

function RunDetailDialog({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const { t, language } = useTranslation()
  const { data: run, isLoading } = useAuditRun(runId)
  const rows: [string, React.ReactNode][] = run
    ? [
        [t('aiAudit.runs.provider'), `${providerLabel(run.provider)} (${run.runtime === 'local_cli' ? t('aiAudit.runs.localCli') : 'API'})`],
        [t('aiAudit.runs.model'), run.model],
        [t('aiAudit.runs.feature'), featureLabel(t, run.feature)],
        [t('aiAudit.runs.started'), formatDateTime(run.started_at, language)],
        [t('aiAudit.runs.duration'), formatMs(run.duration_ms)],
        [t('aiAudit.runs.firstToken'), formatMs(run.first_token_ms)],
        [t('aiAudit.runs.cliVersion'), run.cli_version ?? '—'],
        [t('aiAudit.runs.authMode'), run.auth_mode ?? '—'],
        [t('aiAudit.runs.promptChars'), run.prompt_chars ?? '—'],
        [t('aiAudit.runs.responseChars'), run.response_chars ?? '—'],
        [t('aiAudit.runs.promptHash'), <span key="h" className="font-mono text-xs break-all">{run.prompt_sha256}</span>],
        [t('aiAudit.runs.sources'), (run.source_ids ?? []).join(', ') || '—'],
        [t('aiAudit.runs.estimatedCost'), formatUsd(run.cost_usd_estimated)],
      ]
    : []
  return (
    <Dialog open={!!runId} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('aiAudit.runs.detailTitle')}</DialogTitle>
          <DialogDescription className="font-mono text-xs">{runId}</DialogDescription>
        </DialogHeader>
        {isLoading || !run ? (
          <p className="text-sm text-muted-foreground">{t('common.loading')}</p>
        ) : (
          <div className="space-y-5 text-sm">
            <div className="flex items-center gap-2">
              {run.status === 'success' ? (
                <Badge>{t('aiAudit.runs.success')}</Badge>
              ) : (
                <Badge variant="destructive">
                  {failureLabel(t, run.failure_reason)}
                </Badge>
              )}
            </div>
            {run.error_message && (
              <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                {run.error_message}
                {run.error_truncated ? `\n${t('aiAudit.runs.truncated')}` : ''}
              </pre>
            )}
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
              {rows.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            <div>
              <h3 className="font-medium mb-2">{t('aiAudit.runs.usage')}</h3>
              <table className="w-full text-xs">
                <thead className="text-muted-foreground text-left">
                  <tr>
                    <th className="py-1">{t('aiAudit.runs.model')}</th>
                    <th>{t('aiAudit.tokens.input')}</th>
                    <th>{t('aiAudit.tokens.output')}</th>
                    <th>{t('aiAudit.tokens.cacheRead')}</th>
                    <th>{t('aiAudit.tokens.cacheWrite')}</th>
                    <th>{t('aiAudit.tokens.reasoning')}</th>
                  </tr>
                </thead>
                <tbody>
                  {run.usage.map((u, i) => (
                    <tr key={i} className="border-t">
                      <td className="py-1 font-mono">{u.model}</td>
                      <td>{u.input_tokens}</td>
                      <td>{u.output_tokens}</td>
                      <td>{u.cache_read_tokens}</td>
                      <td>{u.cache_write_tokens}</td>
                      <td>{u.reasoning_tokens}</td>
                    </tr>
                  ))}
                  {run.usage.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-1 text-muted-foreground">{t('aiAudit.noData')}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div>
              <h3 className="font-medium mb-2">{t('aiAudit.runs.events')}</h3>
              <ol className="space-y-1 text-xs">
                {run.events.map((e) => (
                  <li key={e.seq} className="flex gap-2">
                    <span className="text-muted-foreground w-6 text-right">{e.seq}</span>
                    <span className={e.type === 'error' ? 'text-destructive font-mono' : 'font-mono'}>{e.name}</span>
                    {Object.keys(e.detail ?? {}).length > 0 && (
                      <span className="text-muted-foreground font-mono break-all">{JSON.stringify(e.detail)}</span>
                    )}
                  </li>
                ))}
                {run.events.length === 0 && <li className="text-muted-foreground">{t('aiAudit.runs.noEvents')}</li>}
              </ol>
            </div>
            <p className="text-xs text-muted-foreground">{t('aiAudit.privacyNote')}</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function RunsTab() {
  const { t, language } = useTranslation()
  const [page, setPage] = useState(0)
  const [provider, setProvider] = useState(ALL)
  const [status, setStatus] = useState(ALL)
  const [selected, setSelected] = useState<string | null>(null)
  const { data, isLoading } = useAuditRuns({
    limit: PAGE,
    offset: page * PAGE,
    provider: provider === ALL ? undefined : provider,
    status: status === ALL ? undefined : status,
  })
  const total = data?.total ?? 0

  return (
    <Card className="p-6 space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select value={provider} onValueChange={(v) => { setProvider(v); setPage(0) }}>
          <SelectTrigger className="w-48" aria-label={t('aiAudit.runs.provider')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('aiAudit.runs.allProviders')}</SelectItem>
            <SelectItem value="claude_code">Claude Code</SelectItem>
            <SelectItem value="codex_cli">Codex</SelectItem>
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={(v) => { setStatus(v); setPage(0) }}>
          <SelectTrigger className="w-40" aria-label={t('aiAudit.runs.status')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t('aiAudit.runs.allStatuses')}</SelectItem>
            <SelectItem value="success">{t('aiAudit.runs.success')}</SelectItem>
            <SelectItem value="error">{t('aiAudit.runs.error')}</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-sm text-muted-foreground ml-auto">{t('aiAudit.runs.total', { count: total })}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="py-2 pr-3">{t('aiAudit.runs.started')}</th>
              <th className="pr-3">{t('aiAudit.runs.provider')}</th>
              <th className="pr-3">{t('aiAudit.runs.model')}</th>
              <th className="pr-3">{t('aiAudit.runs.feature')}</th>
              <th className="pr-3">{t('aiAudit.runs.status')}</th>
              <th className="pr-3 text-right">{t('aiAudit.runs.duration')}</th>
              <th className="pr-3 text-right">{t('aiAudit.tokens.input')}</th>
              <th className="pr-3 text-right">{t('aiAudit.tokens.output')}</th>
              <th className="text-right">{t('aiAudit.runs.estimatedCost')}</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={9} className="py-4 text-muted-foreground">{t('common.loading')}</td></tr>
            )}
            {!isLoading && (data?.items ?? []).length === 0 && (
              <tr><td colSpan={9} className="py-4 text-muted-foreground">{t('aiAudit.runs.empty')}</td></tr>
            )}
            {(data?.items ?? []).map((r) => (
              <tr
                key={r.id}
                className="border-t cursor-pointer hover:bg-accent"
                tabIndex={0}
                onClick={() => setSelected(r.id)}
                onKeyDown={(e) => e.key === 'Enter' && setSelected(r.id)}
              >
                <td className="py-2 pr-3 whitespace-nowrap">{formatDateTime(r.started_at, language)}</td>
                <td className="pr-3">{providerLabel(r.provider)}</td>
                <td className="pr-3 font-mono text-xs">{r.model}</td>
                <td className="pr-3">{featureLabel(t, r.feature)}</td>
                <td className="pr-3">
                  {r.status === 'success' ? (
                    <Badge>{t('aiAudit.runs.success')}</Badge>
                  ) : (
                    <Badge variant="destructive">
                      {failureLabel(t, r.failure_reason)}
                    </Badge>
                  )}
                </td>
                <td className="pr-3 text-right">{formatMs(r.duration_ms)}</td>
                <td className="pr-3 text-right">{formatTokens(r.input_tokens)}</td>
                <td className="pr-3 text-right">{formatTokens(r.output_tokens)}</td>
                <td className="text-right">{formatUsd(r.cost_usd_estimated)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-end gap-2">
        <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
          {t('aiAudit.prev')}
        </Button>
        <Button size="sm" variant="outline" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>
          {t('aiAudit.next')}
        </Button>
      </div>
      <RunDetailDialog runId={selected} onClose={() => setSelected(null)} />
    </Card>
  )
}
