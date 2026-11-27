'use client'

import { use, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ChevronRight, Library, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  RepoCitationDrawer,
  RepoMarkdown,
} from '@/components/common/RepoCitation'
import { ExportDialog } from '../components/ExportDialog'
import { AppShell } from '@/components/layout/AppShell'
import { repoKbApi, SearchHit } from '@/lib/api/repo-kb'
import { useRepoMutation, useRepoJobs } from '@/lib/hooks/use-repo-kb'
import { repoKbLabel } from '@/lib/repo-kb-labels'
import { useTranslation } from '@/lib/hooks/use-translation'

function HighlightSnippet({ body, terms }: { body: string; terms: string[] }) {
  if (!terms.length) return <>{body}</>
  const expression = new RegExp(
    `(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
    'gi',
  )
  return (
    <>
      {body.split(expression).map((part, index) =>
        index % 2 ? (
          <mark key={index} className="bg-accent text-accent-foreground">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  )
}

export default function KnowledgeBrowser({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const kb = decodeURIComponent(use(params).id)
  const { t } = useTranslation()
  const [slug, setSlug] = useState('index')
  const [tab, setTab] = useState<'wiki' | 'search' | 'discrepancies'>('wiki')
  const [query, setQuery] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [sop, setSop] = useState(false)
  const [module, setModule] = useState('')
  const [differenceModule, setDifferenceModule] = useState('')
  const [differenceStatus, setDifferenceStatus] = useState('')
  const [reference, setReference] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [history, setHistory] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [revision, setRevision] = useState<number | null>(null)
  const [compareRevision, setCompareRevision] = useState<number | null>(null)
  const base = useQuery({
    queryKey: ['repo-kb', kb],
    queryFn: () => repoKbApi.get(kb),
    retry: false,
  })
  const tree = useQuery({
    queryKey: ['repo-kb', kb, 'tree'],
    queryFn: () => repoKbApi.tree(kb),
    retry: false,
  })
  const page = useQuery({
    queryKey: ['repo-kb', kb, 'page', slug],
    queryFn: () => repoKbApi.page(kb, slug),
    retry: false,
  })
  const hits = useQuery({
    queryKey: ['repo-kb', kb, 'search', submitted, sop, module],
    queryFn: () =>
      repoKbApi.search(
        kb,
        submitted,
        sop ? 'sop' : undefined,
        module || undefined,
      ),
    enabled: !!submitted,
    retry: false,
  })
  const differences = useQuery({
    queryKey: ['repo-kb', kb, 'discrepancies'],
    queryFn: () => repoKbApi.discrepancies(kb),
    enabled: tab === 'discrepancies',
    retry: false,
  })
  const versions = useQuery({
    queryKey: ['repo-kb', kb, slug, 'revisions'],
    queryFn: () => repoKbApi.revisions(kb, slug),
    enabled: history,
    retry: false,
  })
  const old = useQuery({
    queryKey: ['repo-kb', kb, slug, 'revision', revision],
    queryFn: () => repoKbApi.revision(kb, slug, revision!),
    enabled: revision !== null,
    retry: false,
  })
  const comparison = useQuery({
    queryKey: ['repo-kb', kb, slug, 'revision', compareRevision],
    queryFn: () => repoKbApi.revision(kb, slug, compareRevision!),
    enabled: compareRevision !== null,
    retry: false,
  })
  const mutate = useRepoMutation((fn: () => Promise<unknown>) => fn())
  const jobs = useRepoJobs(kb)
  const busy = jobs.data?.some((job) =>
    ['queued', 'running'].includes(job.status),
  )
  function navigate(next: string) {
    setSlug(next)
    setTab('wiki')
    setHistory(false)
    setRevision(null)
    setCompareRevision(null)
  }
  const pages = tree.data?.pages || []
  const modules = [
    ...new Set(pages.flatMap((p) => (p.module ? [p.module] : []))),
  ].sort()
  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto">
        <main className="mx-auto max-w-screen-2xl space-y-6 p-6 lg:p-8">
          <header className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <Link
                href="/repo-kb"
                className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"
              >
                <ArrowLeft className="size-4" />
                {t('repoKb.sources')}
              </Link>
              <h1 className="flex items-center gap-3 text-3xl font-semibold">
                <Library />
                {base.data?.name || t('repoKb.browse')}
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                {base.data?.last_build_at
                  ? new Date(base.data.last_build_at).toLocaleString()
                  : t('repoKb.never')}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {Object.entries(base.data?.last_build_commit_set || {})
                  .map(([name, commit]) => `${name}: ${commit.slice(0, 10)}`)
                  .join(' · ')}
              </p>
              {base.data?.stale && (
                <p className="mt-2 text-destructive">{t('repoKb.stale')}</p>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" asChild>
                <Link href="/repo-kb/rules">{t('repoKb.rules')}</Link>
              </Button>
              <Button variant="outline" onClick={() => setExporting(true)}>
                {t('repoKb.exportGit')}
              </Button>
              <Button
                variant="outline"
                onClick={() => mutate.mutate(() => repoKbApi.downloadZip(kb))}
              >
                {t('repoKb.downloadZip')}
              </Button>
              <Button
                disabled={mutate.isPending || busy}
                onClick={() => mutate.mutate(() => repoKbApi.build(kb))}
              >
                {t('repoKb.build')}
              </Button>
            </div>
          </header>
          <section
            className="flex flex-wrap gap-5 rounded-xl border bg-muted/30 p-4"
            aria-label={t('repoKb.health')}
          >
            {[
              ['orphan_pages', 'orphanPages'],
              ['invalid_citations', 'invalidCitations'],
              ['stale_citations', 'staleCitations'],
              ['stale_llm_pages', 'stalePages'],
              ['uncovered_modules', 'uncoveredModules'],
            ].map(([key, label]) => (
              <div key={key} className="text-sm text-muted-foreground">
                {t(repoKbLabel(label))}{' '}
                <strong className="ml-2 text-foreground">
                  {tree.data?.health[key] ?? 0}
                </strong>
              </div>
            ))}
          </section>
          <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
            <aside className="space-y-3 rounded-xl border bg-card p-4">
              <h2 className="font-semibold">{t('repoKb.tree')}</h2>
              <Button
                className="w-full justify-start"
                variant={tab === 'search' ? 'secondary' : 'ghost'}
                onClick={() => setTab('search')}
              >
                <Search className="mr-2 size-4" />
                {t('repoKb.searchButton')}
              </Button>
              <Button
                className="w-full justify-start"
                variant={tab === 'discrepancies' ? 'secondary' : 'ghost'}
                onClick={() => setTab('discrepancies')}
              >
                {t('repoKb.discrepancies')}
              </Button>
              {pages
                .filter((p) => p.kind === 'system' || p.slug === 'index')
                .map((p) => (
                  <Button
                    key={p.slug}
                    className="h-auto w-full justify-start whitespace-normal text-left"
                    variant={slug === p.slug ? 'secondary' : 'ghost'}
                    onClick={() => navigate(p.slug)}
                  >
                    {p.title}
                  </Button>
                ))}
              {modules.map((code) => (
                <details key={code} open className="border-t pt-3">
                  <summary className="cursor-pointer font-medium">
                    {code}
                  </summary>
                  {pages
                    .filter((p) => p.module === code)
                    .map((p) => (
                      <button
                        key={p.slug}
                        className="mt-2 flex w-full items-start gap-1 rounded p-2 text-left text-sm hover:bg-accent"
                        onClick={() => navigate(p.slug)}
                      >
                        <ChevronRight className="mt-1 size-3 shrink-0" />
                        {p.title}
                      </button>
                    ))}
                </details>
              ))}
              <details className="border-t pt-3">
                <summary className="cursor-pointer">
                  {t('repoKb.pages')} ({pages.length})
                </summary>
                {pages
                  .filter(
                    (p) =>
                      p.kind !== 'system' && !p.module && p.slug !== 'index',
                  )
                  .map((p) => (
                    <button
                      key={p.slug}
                      className="mt-1 block w-full rounded p-2 text-left text-sm hover:bg-accent"
                      onClick={() => navigate(p.slug)}
                    >
                      {p.title}
                    </button>
                  ))}
              </details>
            </aside>
            <section className="min-w-0 rounded-xl border bg-card p-5 lg:p-8">
              {tab === 'search' && (
                <div className="space-y-5">
                  <form
                    className="flex flex-wrap gap-2"
                    onSubmit={(e) => {
                      e.preventDefault()
                      setSubmitted(query)
                    }}
                  >
                    <Input
                      className="min-w-48 flex-1"
                      aria-label={t('repoKb.search')}
                      placeholder={t('repoKb.search')}
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                    <Button type="submit">{t('repoKb.searchButton')}</Button>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={sop}
                        onChange={(e) => setSop(e.target.checked)}
                      />
                      {t('repoKb.sopOnly')}
                    </label>
                    <select
                      aria-label={t('repoKb.module')}
                      className="rounded border bg-background px-2"
                      value={module}
                      onChange={(e) => setModule(e.target.value)}
                    >
                      <option value="">{t('repoKb.all')}</option>
                      {modules.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </form>
                  {hits.isFetching && <p>{t('repoKb.loading')}</p>}
                  {hits.error && (
                    <p className="text-destructive">
                      {t('repoKb.failedRequest')}
                    </p>
                  )}
                  {submitted && !hits.isFetching && !hits.data?.length && (
                    <p>{t('common.noResults')}</p>
                  )}
                  {hits.data?.map((hit: SearchHit, i) => (
                    <article
                      key={i}
                      className="space-y-2 rounded-lg border p-4"
                    >
                      <button
                        className="text-left font-medium text-primary"
                        onClick={() =>
                          hit.ref
                            ? setReference(hit.ref)
                            : hit.slug && navigate(hit.slug)
                        }
                      >
                        {hit.path || hit.title}
                      </button>
                      <pre className="whitespace-pre-wrap break-words font-sans text-sm text-muted-foreground">
                        <HighlightSnippet
                          body={hit.body}
                          terms={hit.highlights || []}
                        />
                      </pre>
                      {hit.ref && (
                        <button
                          className="break-all text-left text-xs text-primary"
                          onClick={() => setReference(hit.ref!)}
                        >
                          {hit.ref}
                        </button>
                      )}
                    </article>
                  ))}
                </div>
              )}
              {tab === 'discrepancies' && (
                <div className="space-y-4">
                  <h2 className="text-xl font-semibold">
                    {t('repoKb.discrepancies')}
                  </h2>
                  <div className="flex gap-3">
                    <select
                      aria-label={t('repoKb.module')}
                      className="rounded border bg-background p-2"
                      value={differenceModule}
                      onChange={(e) => setDifferenceModule(e.target.value)}
                    >
                      <option value="">{t('repoKb.all')}</option>
                      {modules.map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                    <select
                      aria-label={t('repoKb.state')}
                      className="rounded border bg-background p-2"
                      value={differenceStatus}
                      onChange={(e) => setDifferenceStatus(e.target.value)}
                    >
                      <option value="">{t('repoKb.all')}</option>
                      {['open', 'confirmed', 'dismissed'].map((s) => (
                        <option key={s} value={s}>
                          {t(repoKbLabel(s))}
                        </option>
                      ))}
                    </select>
                  </div>
                  {differences.data
                    ?.filter(
                      (d) =>
                        (!differenceModule || d.module === differenceModule) &&
                        (!differenceStatus || d.status === differenceStatus),
                    )
                    .map((d) => (
                      <article
                        key={d.id}
                        className="space-y-2 rounded-lg border p-4"
                      >
                        <h3 className="font-medium">
                          {d.module} · {d.program} · {d.kind}
                        </h3>
                        <RepoMarkdown kb={kb}>
                          {d.summary +
                            '\n\n' +
                            [d.spec_cite, d.code_cite]
                              .filter(Boolean)
                              .join(' ')}
                        </RepoMarkdown>
                        <select
                          aria-label={`${t('repoKb.state')} ${d.program}`}
                          className="rounded border bg-background p-2"
                          value={d.status}
                          onChange={(e) =>
                            mutate.mutate(() =>
                              repoKbApi.markDiscrepancy(
                                kb,
                                d.id,
                                e.target.value,
                                d.note || '',
                              ),
                            )
                          }
                        >
                          {['open', 'confirmed', 'dismissed'].map((s) => (
                            <option key={s} value={s}>
                              {t(repoKbLabel(s))}
                            </option>
                          ))}
                        </select>
                        <Input
                          aria-label={t('repoKb.ruleNote')}
                          placeholder={t('repoKb.ruleNote')}
                          defaultValue={d.note || ''}
                          onBlur={(e) => {
                            if (e.target.value !== (d.note || ''))
                              mutate.mutate(() =>
                                repoKbApi.markDiscrepancy(
                                  kb,
                                  d.id,
                                  d.status,
                                  e.target.value,
                                ),
                              )
                          }}
                        />
                      </article>
                    ))}
                </div>
              )}
              {tab === 'wiki' && (
                <>
                  {page.isPending ? (
                    <p>{t('repoKb.loading')}</p>
                  ) : page.error ? (
                    <p className="text-muted-foreground">
                      {t('common.noResults')}
                    </p>
                  ) : (
                    page.data && (
                      <>
                        <div className="mb-4 flex items-center justify-between gap-3">
                          <p className="text-sm text-muted-foreground">
                            {page.data.summary}
                          </p>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setHistory(!history)}
                          >
                            {t('repoKb.history')}
                          </Button>
                        </div>
                        {page.data.stale && (
                          <p className="mb-3 text-destructive">
                            {t('repoKb.stale')}
                          </p>
                        )}
                        {history && (
                          <div className="mb-6 space-y-3 rounded-lg border p-4">
                            <div className="flex flex-wrap gap-2">
                              {versions.data?.map((v) => (
                                <Button
                                  key={v.revision}
                                  size="sm"
                                  variant={
                                    revision === v.revision
                                      ? 'default'
                                      : 'outline'
                                  }
                                  onClick={() => {
                                    setCompareRevision(revision)
                                    setRevision(v.revision)
                                  }}
                                >
                                  v{v.revision}
                                </Button>
                              ))}
                            </div>
                            {old.data && (
                              <>
                                <div className="grid gap-4 md:grid-cols-2">
                                  {comparison.data && (
                                    <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-muted p-3 text-xs">
                                      {comparison.data.body}
                                    </pre>
                                  )}
                                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-muted p-3 text-xs">
                                    {old.data.body}
                                  </pre>
                                </div>
                                {page.data.kind !== 'table' &&
                                  ![
                                    'index',
                                    'system',
                                    'module',
                                    'sop_index',
                                    'discrepancies',
                                  ].includes(page.data.kind) && (
                                    <Button
                                      disabled={mutate.isPending}
                                      onClick={() =>
                                        mutate.mutate(() =>
                                          repoKbApi.restore(
                                            kb,
                                            slug,
                                            revision!,
                                          ),
                                        )
                                      }
                                    >
                                      {t('repoKb.restore')}
                                    </Button>
                                  )}
                              </>
                            )}
                          </div>
                        )}
                        <RepoMarkdown kb={kb} slug={slug} navigate={navigate}>
                          {page.data.body}
                        </RepoMarkdown>
                        <section className="mt-8 space-y-4 border-t pt-6">
                          <h2 className="text-lg font-semibold">
                            {t('repoKb.notes')}
                          </h2>
                          {page.data.notes?.map((n) => (
                            <article
                              key={n.id}
                              className="rounded-lg bg-muted/40 p-4"
                            >
                              {n.stale && (
                                <p className="text-sm text-destructive">
                                  {t('repoKb.stale')}
                                </p>
                              )}
                              <RepoMarkdown kb={kb}>{n.body}</RepoMarkdown>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() =>
                                  mutate.mutate(() =>
                                    repoKbApi.deleteNote(kb, slug, n.id),
                                  )
                                }
                              >
                                {t('common.delete')}
                              </Button>
                            </article>
                          ))}
                          <form
                            onSubmit={(e) => {
                              e.preventDefault()
                              mutate.mutate(async () => {
                                await repoKbApi.addNote(kb, slug, note)
                                setNote('')
                              })
                            }}
                            className="space-y-2"
                          >
                            <Label htmlFor="wiki-note">
                              {t('repoKb.addNote')}
                            </Label>
                            <Textarea
                              id="wiki-note"
                              placeholder={t('repoKb.notePlaceholder')}
                              value={note}
                              onChange={(e) => setNote(e.target.value)}
                            />
                            <Button disabled={!note.trim() || mutate.isPending}>
                              {t('repoKb.addNote')}
                            </Button>
                          </form>
                        </section>
                      </>
                    )
                  )}
                </>
              )}
            </section>
          </div>
          {exporting && (
            <ExportDialog kb={kb} onClose={() => setExporting(false)} />
          )}
          <RepoCitationDrawer
            kb={kb}
            reference={reference}
            onClose={() => setReference(null)}
          />
        </main>
      </div>
    </AppShell>
  )
}
