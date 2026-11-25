'use client'

import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { useRateLimits } from '@/lib/hooks/use-audit'
import { useTranslation } from '@/lib/hooks/use-translation'
import { formatDateTime, providerLabel, limitStatusLabel, windowLabel } from './format'

export function RateLimitsTab() {
  const { t, language } = useTranslation()
  const { data, isLoading } = useRateLimits()
  if (isLoading) return <Card className="p-6 text-sm text-muted-foreground">{t('common.loading')}</Card>
  const items = data ?? []
  return (
    <div className="space-y-4">
      {items.length === 0 && <Card className="p-6 text-sm text-muted-foreground">{t('aiAudit.limits.empty')}</Card>}
      <div className="grid gap-4 md:grid-cols-2">
        {items.map((rl) => (
          <Card key={rl.provider} className="p-6 space-y-4" data-testid={`rate-limit-${rl.provider}`}>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-display text-lg font-semibold">{providerLabel(rl.provider)}</h3>
              {rl.snapshot.plan && <Badge variant="secondary">{rl.snapshot.plan}</Badge>}
              {rl.snapshot.status && (
                <Badge variant={rl.snapshot.status === 'allowed' ? 'default' : 'destructive'}>
                  {limitStatusLabel(t, rl.snapshot.status)}
                </Badge>
              )}
            </div>
            {rl.snapshot.windows.length === 0 && (
              <p className="text-sm text-muted-foreground">{t('aiAudit.limits.noWindows')}</p>
            )}
            {rl.snapshot.windows.map((w) => (
              <div key={w.name} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span>{windowLabel(t, w.name)}</span>
                  <span className="text-muted-foreground">
                    {w.used_percent !== null && w.used_percent !== undefined
                      ? t('aiAudit.limits.used', { percent: Math.round(w.used_percent) })
                      : t('aiAudit.noData')}
                  </span>
                </div>
                <Progress value={w.used_percent ?? 0} aria-label={w.name} />
                {w.resets_at && (
                  <p className="text-xs text-muted-foreground">
                    {t('aiAudit.limits.resetsAt', { time: formatDateTime(w.resets_at, language) })}
                  </p>
                )}
              </div>
            ))}
            <p className="text-xs text-muted-foreground">
              {t('aiAudit.limits.observedAt', { time: formatDateTime(rl.observed_at, language) })}
            </p>
          </Card>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{t('aiAudit.limits.note')}</p>
    </div>
  )
}
