'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { ModelSelector } from '@/components/common/ModelSelector'
import { repoKbApi, FlowProposal } from '@/lib/api/repo-kb'
import { useRepoKBs, useRepoMutation } from '@/lib/hooks/use-repo-kb'
import { repoKbLabel } from '@/lib/repo-kb-labels'
import { useTranslation } from '@/lib/hooks/use-translation'
import { selectClass } from '../components/RuleEditor'

export default function RuleBatches() {
  const { t } = useTranslation()
  const bases = useRepoKBs()
  const stale = useQuery({
    queryKey: ['repo-kb', 'rules', 'stale'],
    queryFn: repoKbApi.staleModules,
    retry: false,
  })
  const [filter, setFilter] = useState('')
  const [source, setSource] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [confirm, setConfirm] = useState(false)
  const [batch, setBatch] = useState('')
  const [flowKB, setFlowKB] = useState('')
  const [flows, setFlows] = useState<FlowProposal[] | null>(null)
  const [chosenFlows, setChosenFlows] = useState<string[]>([])
  const progress = useQuery({
    queryKey: ['repo-kb', 'batch', batch],
    queryFn: () => repoKbApi.batch(batch),
    enabled: !!batch,
    refetchInterval: (query) =>
      query.state.data?.items.some((i) =>
        ['queued', 'running'].includes(i.status),
      )
        ? 2000
        : false,
    retry: false,
  })
  const mutate = useRepoMutation((fn: () => Promise<unknown>) => fn())
  const rows = (stale.data || []).filter(
    (r) =>
      (!filter || r.kb_id === filter) &&
      (!source || r.source_ids.includes(source)),
  )
  const allSources = [
    ...new Set(
      (stale.data || [])
        .filter((r) => !filter || r.kb_id === filter)
        .flatMap((r) => r.source_ids),
    ),
  ]
  const chosen = (stale.data || []).filter((r) =>
    selected.includes(r.kb_id + '|' + r.module),
  )
  const estimate = chosen.reduce((total, r) => total + r.estimated_tokens, 0)
  return (
    <AppShell>
      <main className="flex-1 space-y-6 overflow-y-auto p-6 lg:p-8">
        <header>
          <Link href="/repo-kb" className="text-sm text-muted-foreground">
            ← {t('repoKb.title')}
          </Link>
          <h1 className="mt-3 text-3xl font-semibold">{t('repoKb.rules')}</h1>
          <p className="mt-2 text-muted-foreground">
            {t('repoKb.manualCompile')}
          </p>
        </header>
        <div className="max-w-lg">
          <ModelSelector
            modelType="language"
            value={model}
            onChange={setModel}
            label={t('repoKb.model')}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Label htmlFor="rules-kb">{t('repoKb.selectKb')}</Label>
          <select
            id="rules-kb"
            className={selectClass}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">{t('common.all')}</option>
            {bases.data?.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name}
              </option>
            ))}
          </select>
          <select
            aria-label={t('repoKb.sources')}
            className={selectClass}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">{t('common.all')}</option>
            {allSources.map((id) => (
              <option key={id}>{id}</option>
            ))}
          </select>
          <Button
            variant="outline"
            onClick={() =>
              setSelected(rows.map((r) => r.kb_id + '|' + r.module))
            }
          >
            {t('repoKb.selectAll')}
          </Button>
          <Button
            disabled={!chosen.length || mutate.isPending}
            onClick={() => setConfirm(true)}
          >
            {t('repoKb.compile')} ({chosen.length})
          </Button>
        </div>
        {stale.isError && (
          <p className="text-destructive">{t('repoKb.failedRequest')}</p>
        )}
        <div className="rounded-xl border">
          {rows.map((row) => {
            const key = row.kb_id + '|' + row.module
            return (
              <label
                key={key}
                className="flex items-center justify-between gap-4 border-b p-4 last:border-0"
              >
                <span className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    checked={selected.includes(key)}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? [...selected, key]
                          : selected.filter((k) => k !== key),
                      )
                    }
                  />
                  {row.kb_name} · {row.module}
                </span>
                <span className="text-sm text-muted-foreground">
                  {t('repoKb.estimate', { count: row.estimated_tokens })}
                </span>
              </label>
            )
          })}
          {!rows.length && (
            <p className="p-8 text-muted-foreground">
              {stale.isLoading ? t('repoKb.loading') : t('common.noResults')}
            </p>
          )}
        </div>
        <section className="space-y-3 rounded-xl border p-5">
          <h2 className="text-lg font-medium">{t('repoKb.flow')}</h2>
          <div className="flex gap-3">
            <select
              aria-label={t('repoKb.selectKb')}
              className={selectClass}
              value={flowKB}
              onChange={(e) => setFlowKB(e.target.value)}
            >
              <option value="">{t('repoKb.selectKb')}</option>
              {bases.data?.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            <Button
              disabled={!flowKB || mutate.isPending}
              onClick={() =>
                mutate.mutate(async () => {
                  const data = await repoKbApi.proposeFlows(
                    flowKB,
                    model || undefined,
                  )
                  setFlows(data.flows)
                  setChosenFlows([])
                })
              }
            >
              {t('repoKb.proposeFlows')}
            </Button>
          </div>
        </section>
        {progress.data && (
          <section className="space-y-3 rounded-xl border p-5">
            <div className="flex flex-wrap justify-between gap-3">
              <h2 className="font-medium">{t('repoKb.jobs')}</h2>
              <Button
                variant="outline"
                onClick={() =>
                  mutate.mutate(() => repoKbApi.cancelBatch(batch))
                }
              >
                {t('repoKb.cancelJob')}
              </Button>
            </div>
            <p className="text-sm">
              {['completed', 'failed', 'cancelled', 'queued', 'running']
                .map(
                  (s) =>
                    `${t(repoKbLabel(s))}: ${progress.data?.counts?.[s] ?? 0}`,
                )
                .join(' · ')}
            </p>
            {progress.data.items.map((item, i) => (
              <div
                key={i}
                className="flex items-center justify-between rounded border p-3 text-sm"
              >
                <span>
                  {bases.data?.find((kb) => kb.id === item.kb_id)?.name} ·{' '}
                  {item.value} · {t(repoKbLabel(item.status))} {item.error}
                </span>
                {item.status === 'failed' && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      mutate.mutate(async () => {
                        const data = await repoKbApi.compileBatch(
                          [
                            {
                              kb_id: item.kb_id,
                              [item.kind === 'compile_rules'
                                ? 'modules'
                                : 'flows']: [item.value],
                            },
                          ],
                          model || undefined,
                        )
                        setBatch(data.batch_id)
                      })
                    }
                  >
                    {t('repoKb.retry')}
                  </Button>
                )}
              </div>
            ))}
          </section>
        )}
        <Dialog open={confirm} onOpenChange={setConfirm}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {t('repoKb.compile')} ({chosen.length})
              </DialogTitle>
            </DialogHeader>
            <p>{t('repoKb.estimate', { count: estimate })}</p>
            <p>{chosen.map((r) => `${r.kb_name} / ${r.module}`).join('、')}</p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirm(false)}>
                {t('common.cancel')}
              </Button>
              <Button
                disabled={mutate.isPending}
                onClick={() =>
                  mutate.mutate(async () => {
                    const result = await repoKbApi.compileBatch(
                      chosen.map((r) => ({
                        kb_id: r.kb_id,
                        modules: [r.module],
                      })),
                      model || undefined,
                    )
                    setBatch(result.batch_id)
                    setConfirm(false)
                    setSelected([])
                  })
                }
              >
                {t('repoKb.compile')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Dialog
          open={flows !== null}
          onOpenChange={(open) => {
            if (!open) setFlows(null)
          }}
        >
          <DialogContent className="max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{t('repoKb.proposedFlows')}</DialogTitle>
            </DialogHeader>
            {flows?.map((flow) => (
              <label
                key={flow.title}
                className="flex items-start gap-3 rounded border p-3 text-sm"
              >
                <input
                  type="checkbox"
                  checked={chosenFlows.includes(flow.title)}
                  onChange={(e) =>
                    setChosenFlows(
                      e.target.checked
                        ? [...chosenFlows, flow.title]
                        : chosenFlows.filter((t) => t !== flow.title),
                    )
                  }
                />
                <span className="break-words">
                  <strong>{flow.title}</strong>
                  <span className="mt-2 block text-muted-foreground">
                    {flow.limitations}
                  </span>
                  <span className="mt-1 block break-all text-xs">
                    {flow.evidence}
                  </span>
                </span>
              </label>
            ))}
            <Button
              disabled={!chosenFlows.length || mutate.isPending}
              onClick={() =>
                mutate.mutate(async () => {
                  const data = await repoKbApi.compileBatch(
                    [{ kb_id: flowKB, flows: chosenFlows }],
                    model || undefined,
                  )
                  setBatch(data.batch_id)
                  setFlows(null)
                })
              }
            >
              {t('repoKb.compile')}
            </Button>
          </DialogContent>
        </Dialog>
      </main>
    </AppShell>
  )
}
