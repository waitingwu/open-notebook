'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import { ManageKBDialog } from './components/ManageKBDialog'
import Link from 'next/link'
import {
  BookOpen,
  FolderGit2,
  Plus,
  Settings,
  RefreshCw,
  ShieldCheck,
  Pencil,
  Trash2,
} from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  repoKbApi,
  type RepoSource,
  type RepoKB,
  type VerificationReport,
} from '@/lib/api/repo-kb'
import {
  useRepoKBs,
  useRepoSources,
  useRepoJobs,
  useRepoSettings,
  useRepoMutation,
} from '@/lib/hooks/use-repo-kb'
import { useNotebooks } from '@/lib/hooks/use-notebooks'
import { repoKbLabel } from '@/lib/repo-kb-labels'
import { useTranslation } from '@/lib/hooks/use-translation'
import { SourceDialog, ProtectionDialog } from './components/SourceDialogs'
import {
  SettingsDialog,
  ApplyDefaultsDialog,
} from './components/SettingsDialog'
import { selectClass } from './components/RuleEditor'

function JobSummary({
  result,
  sources,
}: {
  result: Record<string, unknown>
  sources: RepoSource[]
}) {
  const { t } = useTranslation()
  const rows = Object.entries(result).flatMap(([id, value]) => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return []
    const fields = ['added', 'modified', 'deleted', 'reused', 'pages'].flatMap(
      (key) => {
        const number = Reflect.get(value, key)
        return typeof number === 'number' ? [{ key, number }] : []
      },
    )
    return fields.length
      ? [
          {
            id,
            name: sources.find((s) => s.id === id)?.name ?? t('repoKb.build'),
            fields,
          },
        ]
      : []
  })
  return (
    <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
      {typeof result.pages === 'number' && (
        <span>
          {t('repoKb.pages')}: {result.pages}
        </span>
      )}
      {rows.map((row) => (
        <div key={row.id}>
          <span className="mr-2 font-medium">{row.name}</span>
          {row.fields.map((field) => (
            <span key={field.key} className="mr-2">
              {t(repoKbLabel(field.key))} {field.number}
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

function NewKB({
  onClose,
  onCreate,
}: {
  onClose: () => void
  onCreate: (kb: RepoKB) => void
}) {
  const { t } = useTranslation()
  const notebooks = useNotebooks()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<'global' | 'notebook'>('global')
  const [owner, setOwner] = useState('')
  const save = useRepoMutation(async () => {
    const kb = await repoKbApi.create({
      name,
      scope,
      owner_notebook: owner || undefined,
    })
    onCreate(kb)
    onClose()
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('repoKb.create')}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate(undefined)
          }}
        >
          <div className="space-y-1">
            <Label htmlFor="kb-name">{t('repoKb.name')}</Label>
            <Input
              id="kb-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="kb-scope">{t('repoKb.scope')}</Label>
            <select
              id="kb-scope"
              className={`${selectClass} w-full`}
              value={scope}
              onChange={(e) =>
                setScope(e.target.value as 'global' | 'notebook')
              }
            >
              <option value="global">{t('repoKb.global')}</option>
              <option value="notebook">{t('repoKb.private')}</option>
            </select>
          </div>
          {scope === 'notebook' && (
            <div className="space-y-1">
              <Label htmlFor="kb-owner">{t('repoKb.chooseNotebook')}</Label>
              <select
                id="kb-owner"
                className={`${selectClass} w-full`}
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                required
              >
                <option value="">{t('repoKb.chooseNotebook')}</option>
                {notebooks.data?.map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              disabled={
                save.isPending ||
                !name.trim() ||
                (scope === 'notebook' && !owner)
              }
            >
              {t('common.create')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SyncDialog({
  sources,
  onClose,
}: {
  sources: RepoSource[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [mode, setMode] = useState<'auto' | 'full'>('auto')
  const start = useRepoMutation(async () => {
    await repoKbApi.sync(sources, mode)
    onClose()
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('repoKb.syncTitle')}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{t('repoKb.syncHelp')}</p>
        {sources.map((source) => (
          <div key={source.id} className="rounded-lg border p-3">
            <h3 className="font-medium">{source.name}</h3>
            <p className="break-all text-xs text-muted-foreground">
              {source.path}
            </p>
            <ul className="mt-2 text-sm">
              {source.protected
                .filter((r) => r.enabled)
                .map((rule, index) => (
                  <li key={index}>{rule.pattern}</li>
                ))}
              {!source.protected.some((r) => r.enabled) && (
                <li>{t('repoKb.none')}</li>
              )}
            </ul>
          </div>
        ))}
        <select
          aria-label={t('repoKb.sync')}
          className={selectClass}
          value={mode}
          onChange={(e) => setMode(e.target.value as 'auto' | 'full')}
        >
          <option value="auto">{t('repoKb.auto')}</option>
          <option value="full">{t('repoKb.full')}</option>
        </select>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={start.isPending}
            onClick={() => start.mutate(undefined)}
          >
            {t('repoKb.startSync')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Workspace({ kb }: { kb: string }) {
  const { t } = useTranslation()
  const sources = useRepoSources(kb)
  const jobs = useRepoJobs(kb)
  const settings = useRepoSettings()
  const [selected, setSelected] = useState<string[]>([])
  const [editor, setEditor] = useState<RepoSource | 'new' | null>(null)
  const [protection, setProtection] = useState<RepoSource | null>(null)
  const [sync, setSync] = useState<RepoSource[] | null>(null)
  const [deleting, setDeleting] = useState<RepoSource | null>(null)
  const [apply, setApply] = useState(false)
  const [report, setReport] = useState<VerificationReport | null>(null)
  const build = useRepoMutation(() => repoKbApi.build(kb))
  const verify = useRepoMutation(async () =>
    setReport(await repoKbApi.verify(kb)),
  )
  const remove = useRepoMutation(async () => {
    if (deleting) await repoKbApi.deleteSource(deleting.id)
    setDeleting(null)
  })
  const cancel = useRepoMutation((id: string) => repoKbApi.cancel(id))
  const retry = useRepoMutation((id: string) => repoKbApi.retry(id))
  const chosen = (sources.data ?? []).filter((source) =>
    selected.includes(source.id),
  )
  const busy = jobs.data?.some((job) =>
    ['running', 'queued'].includes(job.status),
  )
  const toggle = (id: string) =>
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((s) => s !== id)
        : [...previous, id],
    )
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setEditor('new')} disabled={busy}>
          <Plus className="mr-2 size-4" />
          {t('repoKb.addSource')}
        </Button>
        <Button
          variant="outline"
          disabled={!chosen.length || busy}
          onClick={() => setSync(chosen)}
        >
          {t('repoKb.syncSelected')}
        </Button>
        <Button
          variant="outline"
          disabled={!chosen.length || busy || !settings.data}
          onClick={() => setApply(true)}
        >
          {t('repoKb.applyDefaults')}
        </Button>
        <Button
          variant="outline"
          disabled={busy || build.isPending}
          onClick={() => build.mutate(undefined)}
        >
          <RefreshCw className="mr-2 size-4" />
          {t('repoKb.build')}
        </Button>
        <Button variant="ghost" onClick={() => verify.mutate(undefined)}>
          <ShieldCheck className="mr-2 size-4" />
          {t('repoKb.verify')}
        </Button>
        <Button asChild variant="ghost">
          <Link href={`/repo-kb/${encodeURIComponent(kb)}`}>
            <BookOpen className="mr-2 size-4" />
            {t('repoKb.browse')}
          </Link>
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{t('repoKb.readOnly')}</p>
      {sources.isError && (
        <p role="alert" className="text-destructive">
          {t('repoKb.failedRequest')}
        </p>
      )}
      <div className="overflow-x-auto rounded-xl border">
        <table className="w-full text-left text-sm">
          <thead className="border-b bg-muted/40">
            <tr>
              <th className="p-3">
                <input
                  aria-label={t('repoKb.selectAll')}
                  type="checkbox"
                  checked={
                    !!sources.data?.length &&
                    chosen.length === sources.data.length
                  }
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? (sources.data ?? []).map((s) => s.id)
                        : [],
                    )
                  }
                />
              </th>
              {[
                'name',
                'protected',
                'lastSync',
                'commit',
                'files',
                'state',
                'actions',
              ].map((key) => (
                <th className="p-3 font-medium" key={key}>
                  {t(repoKbLabel(key))}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sources.data?.map((source) => (
              <tr key={source.id} className="border-b last:border-0">
                <td className="p-3">
                  <input
                    aria-label={`${t('repoKb.select')} ${source.name}`}
                    type="checkbox"
                    checked={selected.includes(source.id)}
                    onChange={() => toggle(source.id)}
                  />
                </td>
                <td className="max-w-64 p-3">
                  <div className="font-medium">{source.name}</div>
                  <div className="break-all text-xs text-muted-foreground">
                    {source.path}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {t(repoKbLabel(source.role))}
                  </span>
                </td>
                <td className="max-w-40 p-3">
                  <div className="break-all text-xs">
                    {source.protected
                      .filter((r) => r.enabled)
                      .map((r) => r.pattern)
                      .join(', ') || t('repoKb.none')}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => setProtection(source)}
                  >
                    {t('common.edit')}
                  </Button>
                </td>
                <td className="whitespace-nowrap p-3 text-xs">
                  {source.last_synced_at
                    ? new Date(source.last_synced_at).toLocaleString()
                    : '—'}
                </td>
                <td
                  className="p-3 font-mono text-xs"
                  title={source.last_commit}
                >
                  {source.last_commit?.slice(0, 10) || '—'}
                </td>
                <td className="p-3 tabular-nums">{source.file_count}</td>
                <td className="p-3">
                  <span
                    className={`rounded-full px-2 py-1 text-xs ${source.status === 'error' ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground'}`}
                  >
                    {t(repoKbLabel(source.status), {
                      defaultValue: source.status,
                    })}
                  </span>
                  {source.last_error && (
                    <p className="mt-2 text-xs text-destructive">
                      {source.last_error}
                    </p>
                  )}
                </td>
                <td className="p-3">
                  <div className="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => setSync([source])}
                    >
                      {t('repoKb.sync')}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={busy}
                      aria-label={`${t('common.edit')} ${source.name}`}
                      onClick={() => setEditor(source)}
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={busy}
                      aria-label={`${t('common.delete')} ${source.name}`}
                      onClick={() => setDeleting(source)}
                    >
                      <Trash2 className="size-4 text-destructive" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
            {!sources.data?.length && (
              <tr>
                <td
                  colSpan={8}
                  className="p-10 text-center text-muted-foreground"
                >
                  {sources.isLoading
                    ? t('repoKb.loading')
                    : t('repoKb.noSources')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t('repoKb.jobs')}</h2>
        {!jobs.data?.length && (
          <p className="text-sm text-muted-foreground">{t('repoKb.noJobs')}</p>
        )}
        {jobs.data?.map((job) => (
          <div key={job.id} className="space-y-2 rounded-lg border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-medium">
                  {t(repoKbLabel(`kind_${job.kind}`), {
                    defaultValue: job.kind,
                  })}
                </span>
                <span className="ml-3 text-sm text-muted-foreground">
                  {t(repoKbLabel(job.status), { defaultValue: job.status })}
                </span>
                <span className="ml-3 text-xs text-muted-foreground">
                  {new Date(job.created).toLocaleString()}
                </span>
              </div>
              {['queued', 'running'].includes(job.status) && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => cancel.mutate(job.id)}
                >
                  {t('repoKb.cancelJob')}
                </Button>
              )}
              {['failed', 'cancelled'].includes(job.status) && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={() => retry.mutate(job.id)}
                >
                  {t('repoKb.retry')}
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {t(repoKbLabel(`stage_${job.progress.stage}`), {
                defaultValue: job.progress.stage ?? '',
              })}{' '}
              · {job.progress.done ?? 0}/{job.progress.total ?? 0}
            </p>
            {job.progress.total ? (
              <progress
                className="h-2 w-full accent-foreground"
                value={job.progress.done ?? 0}
                max={job.progress.total}
              />
            ) : null}
            {job.error && (
              <p className="text-sm text-destructive">{job.error}</p>
            )}
            {job.status === 'completed' && (
              <JobSummary result={job.result} sources={sources.data ?? []} />
            )}
          </div>
        ))}
      </section>
      {editor && (
        <SourceDialog
          kb={kb}
          source={editor === 'new' ? undefined : editor}
          defaults={settings.data?.default_protected ?? []}
          onClose={() => setEditor(null)}
        />
      )}
      {protection && (
        <ProtectionDialog
          source={protection}
          onClose={() => setProtection(null)}
        />
      )}
      {sync && <SyncDialog sources={sync} onClose={() => setSync(null)} />}
      {apply && settings.data && (
        <ApplyDefaultsDialog
          sources={chosen}
          settings={settings.data}
          onClose={() => setApply(false)}
        />
      )}
      {deleting && (
        <Dialog open onOpenChange={(open) => !open && setDeleting(null)}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {t('repoKb.deleteSource')} · {deleting.name}
              </DialogTitle>
            </DialogHeader>
            <p>{t('repoKb.deleteHelp')}</p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>
                {t('common.cancel')}
              </Button>
              <Button
                variant="destructive"
                disabled={remove.isPending}
                onClick={() => remove.mutate(undefined)}
              >
                {t('common.delete')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {report !== null && (
        <Dialog open onOpenChange={(open) => !open && setReport(null)}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t('repoKb.verify')}</DialogTitle>
            </DialogHeader>
            <div className="max-h-96 space-y-3 overflow-auto">
              <p>{t(report.valid ? 'repoKb.valid' : 'repoKb.invalid')}</p>
              {report.rules.map((rule, index) => (
                <div className="rounded-lg border p-3 text-sm" key={index}>
                  <p className="font-medium">
                    {rule.source_name} · {rule.pattern}
                  </p>
                  <p>
                    {t('repoKb.storedFiles')}: {rule.stored_files} ·{' '}
                    {t('repoKb.storedChunks')}: {rule.stored_chunks}
                  </p>
                  <p>
                    {t('repoKb.historicalAccesses')}: {rule.historical_accesses}{' '}
                    · {t('repoKb.policyTest')}:{' '}
                    {t(
                      rule.policy_self_test ? 'repoKb.valid' : 'repoKb.invalid',
                    )}
                  </p>
                </div>
              ))}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}

export default function RepoKBPage() {
  const { t } = useTranslation()
  const params = useParams()
  const bases = useRepoKBs()
  const settings = useRepoSettings()
  const [selected, setSelected] = useState('')
  const [creating, setCreating] = useState(false)
  const [configuring, setConfiguring] = useState(false)
  const [managing, setManaging] = useState(false)
  const [scopeFilter, setScopeFilter] = useState('')
  const kb =
    selected ||
    (typeof params.id === 'string' ? decodeURIComponent(params.id) : '') ||
    bases.data?.[0]?.id ||
    ''
  const current = bases.data?.find((base) => base.id === kb)
  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <main className="mx-auto max-w-7xl space-y-7 p-6">
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="mb-2 flex items-center gap-2 text-muted-foreground">
                <FolderGit2 className="size-5" />
                <span className="text-sm">CaBook</span>
              </div>
              <h1 className="font-display text-3xl font-bold tracking-tight">
                {t('repoKb.title')}
              </h1>
              <p className="mt-2 max-w-xl text-muted-foreground">
                {t('repoKb.description')}
              </p>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={!settings.data}
                onClick={() => setConfiguring(true)}
              >
                <Settings className="mr-2 size-4" />
                {t('repoKb.settings')}
              </Button>
              <Button onClick={() => setCreating(true)}>
                <Plus className="mr-2 size-4" />
                {t('repoKb.create')}
              </Button>
            </div>
          </header>
          {settings.data?.externally_bound &&
            !settings.data.effective_allowed_roots?.length && (
              <p className="rounded-lg bg-warn-tint p-3 text-sm text-warn">
                {t('repoKb.externallyBoundWarning')}
              </p>
            )}
          <section className="space-y-3">
            <select
              aria-label={t('repoKb.scope')}
              className={selectClass}
              value={scopeFilter}
              onChange={(e) => setScopeFilter(e.target.value)}
            >
              <option value="">{t('common.all')}</option>
              <option value="global">{t('repoKb.global')}</option>
              <option value="notebook">{t('repoKb.private')}</option>
            </select>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {bases.data
                ?.filter((base) => !scopeFilter || base.scope === scopeFilter)
                .map((base) => (
                  <button
                    key={base.id}
                    className={`space-y-2 rounded-xl border p-4 text-left ${kb === base.id ? 'border-primary bg-muted/30' : 'bg-card'}`}
                    onClick={() => setSelected(base.id)}
                  >
                    <h2 className="font-medium">{base.name}</h2>
                    <p className="text-xs text-muted-foreground">
                      {t(
                        base.scope === 'global'
                          ? 'repoKb.global'
                          : 'repoKb.private',
                      )}
                    </p>
                    <p className="text-sm">
                      {t('repoKb.sources')}: {base.source_count ?? 0} ·{' '}
                      {t('repoKb.files')}: {base.file_count ?? 0}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {t('repoKb.discrepancies')}:{' '}
                      {base.open_discrepancies ?? 0} ·{' '}
                      {base.last_synced_at
                        ? new Date(base.last_synced_at).toLocaleString()
                        : t('repoKb.never')}
                    </p>
                  </button>
                ))}
            </div>
          </section>
          {bases.isError && (
            <p role="alert" className="text-destructive">
              {t('repoKb.failedRequest')}
            </p>
          )}
          {kb ? (
            <>
              <div className="flex items-center gap-3 border-b pb-4">
                <Label htmlFor="kb-choice">{t('repoKb.selectKb')}</Label>
                <select
                  id="kb-choice"
                  className={`${selectClass} min-w-64`}
                  value={kb}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  {bases.data?.map((base) => (
                    <option key={base.id} value={base.id}>
                      {base.name}
                    </option>
                  ))}
                </select>
                <Button variant="outline" onClick={() => setManaging(true)}>
                  {t('common.edit')}
                </Button>
              </div>
              <Workspace key={kb} kb={kb} />
            </>
          ) : (
            <div className="rounded-2xl border border-dashed p-16 text-center text-muted-foreground">
              {bases.isLoading ? t('repoKb.loading') : t('repoKb.empty')}
            </div>
          )}
          {creating && (
            <NewKB
              onClose={() => setCreating(false)}
              onCreate={(base) => setSelected(base.id)}
            />
          )}
          {configuring && settings.data && (
            <SettingsDialog
              initial={settings.data}
              onClose={() => setConfiguring(false)}
            />
          )}
          {managing && current && (
            <ManageKBDialog kb={current} onClose={() => setManaging(false)} />
          )}
        </main>
      </div>
    </AppShell>
  )
}
