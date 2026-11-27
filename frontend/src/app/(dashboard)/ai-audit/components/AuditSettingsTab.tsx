'use client'

import { useState } from 'react'
import { Download, Trash2 } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { auditApi, AuditSettings, ModelRate } from '@/lib/api/audit'
import {
  useApplyRetention,
  useAuditSettings,
  useClearAuditLogs,
  useUpdateAuditSettings,
} from '@/lib/hooks/use-audit'
import { useTranslation } from '@/lib/hooks/use-translation'

type RateRow = { model: string; input: string; output: string; cache_read: string }

function toRows(data: AuditSettings | undefined): RateRow[] {
  return Object.entries(data?.pricing ?? {}).map(([model, r]) => ({
    model,
    input: String(r.input ?? ''),
    output: String(r.output ?? ''),
    cache_read: r.cache_read === null || r.cache_read === undefined ? '' : String(r.cache_read),
  }))
}

export function AuditSettingsTab() {
  const { data } = useAuditSettings()
  // Re-mount the form when saved settings change so it starts from them.
  return <AuditSettingsForm key={JSON.stringify(data ?? null)} initial={data} />
}

function AuditSettingsForm({ initial }: { initial: AuditSettings | undefined }) {
  const { t } = useTranslation()
  const update = useUpdateAuditSettings()
  const retention = useApplyRetention()
  const clear = useClearAuditLogs()
  const [eventDays, setEventDays] = useState(String(initial?.event_retention_days ?? 30))
  const [runDays, setRunDays] = useState(String(initial?.run_retention_days ?? 365))
  const [rates, setRates] = useState<RateRow[]>(() => toRows(initial))
  const [exporting, setExporting] = useState(false)

  const save = () => {
    const pricing: Record<string, ModelRate> = {}
    for (const r of rates) {
      if (!r.model.trim()) continue
      pricing[r.model.trim()] = {
        input: Number(r.input) || 0,
        output: Number(r.output) || 0,
        cache_read: r.cache_read === '' ? null : Number(r.cache_read),
      }
    }
    update.mutate({
      event_retention_days: Number(eventDays),
      run_retention_days: Number(runDays),
      pricing,
    })
  }

  const download = async (format: 'csv' | 'json') => {
    setExporting(true)
    try {
      const blob = await auditApi.exportRuns(format, Number(runDays) || 365)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `ai-runs.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }

  const setRate = (i: number, key: keyof RateRow, value: string) =>
    setRates((prev) => prev.map((r, j) => (j === i ? { ...r, [key]: value } : r)))

  return (
    <div className="space-y-4">
      <Card className="p-6 space-y-4">
        <h3 className="font-display text-lg font-semibold">{t('aiAudit.settings.retentionTitle')}</h3>
        <p className="text-sm text-muted-foreground">{t('aiAudit.settings.retentionDesc')}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor="event-days">{t('aiAudit.settings.eventDays')}</Label>
            <Input id="event-days" type="number" min={1} value={eventDays} onChange={(e) => setEventDays(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="run-days">{t('aiAudit.settings.runDays')}</Label>
            <Input id="run-days" type="number" min={1} value={runDays} onChange={(e) => setRunDays(e.target.value)} />
          </div>
        </div>
        <h3 className="font-display text-lg font-semibold pt-2">{t('aiAudit.settings.pricingTitle')}</h3>
        <p className="text-sm text-muted-foreground">{t('aiAudit.settings.pricingDesc')}</p>
        <div className="space-y-2">
          {rates.map((r, i) => (
            <div key={i} className="grid grid-cols-[2fr_1fr_1fr_1fr_auto] gap-2 items-center">
              <Input aria-label={t('aiAudit.runs.model')} placeholder="gpt-..." value={r.model} onChange={(e) => setRate(i, 'model', e.target.value)} />
              <Input aria-label={t('aiAudit.tokens.input')} placeholder={t('aiAudit.tokens.input')} type="number" min={0} step="any" value={r.input} onChange={(e) => setRate(i, 'input', e.target.value)} />
              <Input aria-label={t('aiAudit.tokens.output')} placeholder={t('aiAudit.tokens.output')} type="number" min={0} step="any" value={r.output} onChange={(e) => setRate(i, 'output', e.target.value)} />
              <Input aria-label={t('aiAudit.tokens.cacheRead')} placeholder={t('aiAudit.tokens.cacheRead')} type="number" min={0} step="any" value={r.cache_read} onChange={(e) => setRate(i, 'cache_read', e.target.value)} />
              <Button size="icon" variant="ghost" aria-label={t('common.remove')} onClick={() => setRates(rates.filter((_, j) => j !== i))}>
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
          <Button size="sm" variant="outline" onClick={() => setRates([...rates, { model: '', input: '', output: '', cache_read: '' }])}>
            {t('aiAudit.settings.addRate')}
          </Button>
        </div>
        <div className="flex gap-2 pt-2">
          <Button onClick={save} disabled={update.isPending}>{t('common.save')}</Button>
          <Button variant="outline" onClick={() => retention.mutate()} disabled={retention.isPending}>
            {t('aiAudit.settings.applyNow')}
          </Button>
        </div>
      </Card>

      <Card className="p-6 space-y-3">
        <h3 className="font-display text-lg font-semibold">{t('aiAudit.settings.exportTitle')}</h3>
        <p className="text-sm text-muted-foreground">{t('aiAudit.settings.exportDesc')}</p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => download('csv')} disabled={exporting}>
            <Download className="size-4" />CSV
          </Button>
          <Button variant="outline" onClick={() => download('json')} disabled={exporting}>
            <Download className="size-4" />JSON
          </Button>
        </div>
      </Card>

      <Card className="p-6 space-y-3">
        <h3 className="font-display text-lg font-semibold">{t('aiAudit.settings.clearTitle')}</h3>
        <p className="text-sm text-muted-foreground">{t('aiAudit.settings.clearDesc')}</p>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" disabled={clear.isPending}>
              <Trash2 className="size-4" />
              {t('aiAudit.settings.clearButton')}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('aiAudit.settings.clearConfirmTitle')}</AlertDialogTitle>
              <AlertDialogDescription>{t('aiAudit.settings.clearConfirmDesc')}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
              <AlertDialogAction onClick={() => clear.mutate()}>{t('aiAudit.settings.clearButton')}</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </Card>
    </div>
  )
}
