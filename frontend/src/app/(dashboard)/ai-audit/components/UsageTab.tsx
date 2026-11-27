'use client'

import { useState } from 'react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useUsageSummary } from '@/lib/hooks/use-audit'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { UsageBucket } from '@/lib/api/audit'
import { formatTokens, formatUsd, providerLabel, featureLabel } from './format'

const RANGES = [7, 30, 90]

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
      {hint && <p className="text-xs text-muted-foreground mt-1">{hint}</p>}
    </div>
  )
}

function BreakdownTable({ title, rows, labelFor }: { title: string; rows: (UsageBucket & { key: string })[]; labelFor: (k: string) => string }) {
  const { t } = useTranslation()
  return (
    <div>
      <h3 className="font-medium mb-2">{title}</h3>
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="py-1 pr-3" />
            <th className="pr-3 text-right">{t('aiAudit.usage.runs')}</th>
            <th className="pr-3 text-right">{t('aiAudit.usage.errors')}</th>
            <th className="pr-3 text-right">{t('aiAudit.tokens.input')}</th>
            <th className="pr-3 text-right">{t('aiAudit.tokens.output')}</th>
            <th className="text-right">{t('aiAudit.runs.estimatedCost')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t">
              <td className="py-1 pr-3">{labelFor(r.key)}</td>
              <td className="pr-3 text-right">{r.runs}</td>
              <td className="pr-3 text-right">{r.errors}</td>
              <td className="pr-3 text-right">{formatTokens(r.input_tokens)}</td>
              <td className="pr-3 text-right">{formatTokens(r.output_tokens)}</td>
              <td className="text-right">
                {formatUsd(r.cost_usd_estimated)}
                {r.uncosted_runs > 0 && <span className="text-muted-foreground"> *</span>}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td colSpan={6} className="py-2 text-muted-foreground">{t('aiAudit.noData')}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export function UsageTab() {
  const { t } = useTranslation()
  const [days, setDays] = useState(30)
  const { data, isLoading } = useUsageSummary(days)

  if (isLoading || !data) {
    return <Card className="p-6 text-sm text-muted-foreground">{t('common.loading')}</Card>
  }
  const max = Math.max(1, ...data.daily.map((d) => d.input_tokens + d.output_tokens))
  const totals = data.totals

  return (
    <Card className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        {RANGES.map((r) => (
          <Button key={r} size="sm" variant={r === days ? 'default' : 'outline'} onClick={() => setDays(r)}>
            {t('aiAudit.usage.lastDays', { count: r })}
          </Button>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t('aiAudit.usage.runs')} value={String(totals.runs)} hint={t('aiAudit.usage.errorsHint', { count: totals.errors })} />
        <Stat label={t('aiAudit.tokens.input')} value={formatTokens(totals.input_tokens)} hint={t('aiAudit.usage.cacheHint', { read: formatTokens(totals.cache_read_tokens), write: formatTokens(totals.cache_write_tokens) })} />
        <Stat label={t('aiAudit.tokens.output')} value={formatTokens(totals.output_tokens)} hint={t('aiAudit.usage.reasoningHint', { count: formatTokens(totals.reasoning_tokens) })} />
        <Stat
          label={t('aiAudit.usage.equivalentCost')}
          value={formatUsd(totals.cost_usd_estimated)}
          hint={totals.uncosted_runs > 0 ? t('aiAudit.usage.uncostedHint', { count: totals.uncosted_runs }) : t('aiAudit.usage.costHint')}
        />
      </div>
      <div>
        <h3 className="font-medium mb-2">{t('aiAudit.usage.dailyTokens')}</h3>
        <div className="flex items-end gap-[2px] h-40 border-b" role="img" aria-label={t('aiAudit.usage.dailyTokens')}>
          {data.daily.map((d) => {
            const total = d.input_tokens + d.output_tokens
            return (
              <div
                key={d.date}
                className="flex-1 flex flex-col justify-end h-full"
                title={`${d.date}: ${formatTokens(d.input_tokens)} in / ${formatTokens(d.output_tokens)} out · ${d.runs} runs`}
              >
                <div className="bg-teal rounded-t-sm" style={{ height: `${(d.output_tokens / max) * 100}%` }} />
                <div className="bg-teal-tint" style={{ height: `${(d.input_tokens / max) * 100}%`, minHeight: total > 0 ? 2 : 0 }} />
              </div>
            )
          })}
        </div>
        <div className="flex justify-between text-xs text-muted-foreground mt-1">
          <span>{data.daily[0]?.date}</span>
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1"><span className="inline-block size-2 bg-teal-tint" />{t('aiAudit.tokens.input')}</span>
            <span className="flex items-center gap-1"><span className="inline-block size-2 bg-teal" />{t('aiAudit.tokens.output')}</span>
          </span>
          <span>{data.daily[data.daily.length - 1]?.date}</span>
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <BreakdownTable
          title={t('aiAudit.usage.byModel')}
          rows={data.by_model}
          labelFor={(k) => {
            const [p, ...rest] = k.split(' · ')
            return `${providerLabel(p)} · ${rest.join(' · ')}`
          }}
        />
        <BreakdownTable
          title={t('aiAudit.usage.byFeature')}
          rows={data.by_feature}
          labelFor={(k) => featureLabel(t, k)}
        />
      </div>
      <p className="text-xs text-muted-foreground">{t('aiAudit.usage.costFootnote')}</p>
    </Card>
  )
}
