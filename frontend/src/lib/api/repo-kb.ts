import apiClient from './client'

export interface ProtectedRule {
  kind: 'dir_name' | 'glob'
  pattern: string
  enabled: boolean
  note?: string | null
}
export interface RepoKB {
  id: string
  name: string
  description?: string
  scope: 'global' | 'notebook'
  owner_notebook?: string
  stale: boolean
  last_build_at?: string
  last_build_commit_set?: Record<string, string>
  source_count?: number
  file_count?: number
  open_discrepancies?: number
  last_synced_at?: string
}
export interface RepoSource {
  id: string
  kb: string
  name: string
  path: string
  role: 'doc' | 'src'
  include: string[]
  exclude: string[]
  protected: ProtectedRule[]
  enabled: boolean
  last_commit?: string
  last_synced_at?: string
  file_count: number
  status: string
  last_error?: string
  config_hash: string
  needs_full: boolean
}
export type SourceInput = Pick<
  RepoSource,
  'name' | 'path' | 'role' | 'include' | 'exclude' | 'protected'
>
export interface RepoJob {
  id: string
  source?: string
  kind: string
  status: string
  command_id?: string
  progress: { stage?: string; done?: number; total?: number }
  result: Record<string, unknown>
  error?: string
  created: string
}
export interface RepoSettings {
  confirm_patterns?: string[]
  reason?: string
  default_protected: ProtectedRule[]
  allowed_roots: string[]
  selector_timeout: number
  effective_allowed_roots?: string[]
  externally_bound?: boolean
}
export interface Preview {
  files: number
  by_extension: Record<string, number>
  protected_directories: { pattern: string; count: number }[]
  warnings: string[]
}
export interface FolderListing {
  path: string
  parent: string | null
  directories: { name: string; path: string; is_git_repo: boolean }[]
}
export interface WikiPage {
  id: string
  slug: string
  kind: string
  title: string
  summary: string
  body: string
  module?: string
  revision: number
  stale: boolean
  citations: { ref: string }[]
  notes?: WikiNote[]
}
export interface WikiNote {
  id: string
  body: string
  stale: boolean
  anchor_heading?: string
}
export interface CitationResult {
  valid: boolean
  status: string
  stale?: boolean
  ref: string
  file_commit?: string
  lines?: { number: number; text: string; highlight: boolean }[]
}
export interface SearchHit {
  highlights?: string[]
  path?: string
  repo?: string
  title?: string
  body: string
  ref?: string
  slug?: string
  score: number
}
export interface VerificationReport {
  valid: boolean
  os_evidence_required: boolean
  rules: {
    source_name: string
    pattern: string
    stored_files: number
    stored_chunks: number
    historical_accesses: number
    wiki_references: number
    ai_references: number
    policy_self_test: boolean
  }[]
}
export interface Discrepancy {
  id: string
  module: string
  program: string
  kind: string
  summary: string
  spec_cite?: string
  code_cite?: string
  status: string
  note?: string
}
export interface WikiRevision {
  revision: number
  body?: string
  summary: string
  generated_by: string
  created: string
}
export interface StaleModule {
  kb_id: string
  kb_name: string
  module: string
  source_ids: string[]
  source_names?: Record<string, string>
  reason: string
  estimated_tokens: number
}
export interface FlowProposal {
  title: string
  evidence: string
  limitations: string
}
export interface CompileBatch {
  id: string
  items: {
    kb_id: string
    kind: string
    value: string
    status: string
    job_id?: string
    error?: string
  }[]
  counts?: Record<string, number>
}
export interface ExportConfig {
  enabled: boolean
  repo_path: string
  branch: string
  subdir: string
  last_export_commit?: string
  last_error?: string
}
const base = '/repo-kb'
const id = encodeURIComponent

export const repoKbApi = {
  deleteRelatedChats: async (kb: string) =>
    (
      await apiClient.delete(`${base}/kbs/${id(kb)}/chats`, {
        params: { confirmed: true },
      })
    ).data,
  exclusionAudit: async (source: string) =>
    (
      await apiClient.get<
        {
          id: string
          ts: string
          action: string
          before?: { rules?: ProtectedRule[] }
          after?: { rules?: ProtectedRule[] }
          reason?: string
        }[]
      >(`${base}/sources/${id(source)}/protected/audit`)
    ).data,
  mountedNotebooks: async (kb: string) =>
    (
      await apiClient.get<{ id: string; name: string }[]>(
        `${base}/kbs/${id(kb)}/mounted-notebooks`,
      )
    ).data,
  list: async (notebookId?: string) =>
    (
      await apiClient.get<RepoKB[]>(`${base}/kbs`, {
        params: { notebook_id: notebookId },
      })
    ).data,
  create: async (data: {
    name: string
    description?: string
    scope: 'global' | 'notebook'
    owner_notebook?: string
  }) => (await apiClient.post<RepoKB>(`${base}/kbs`, data)).data,
  get: async (kb: string) =>
    (await apiClient.get<RepoKB>(`${base}/kbs/${id(kb)}`)).data,
  sources: async (kb: string) =>
    (await apiClient.get<RepoSource[]>(`${base}/kbs/${id(kb)}/sources`)).data,
  addSource: async (kb: string, data: SourceInput) =>
    (await apiClient.post<RepoSource>(`${base}/kbs/${id(kb)}/sources`, data))
      .data,
  editSource: async (
    source: string,
    data: Partial<Omit<SourceInput, 'protected'>>,
  ) =>
    (await apiClient.patch<RepoSource>(`${base}/sources/${id(source)}`, data))
      .data,
  deleteSource: async (source: string) =>
    (
      await apiClient.delete(`${base}/sources/${id(source)}`, {
        params: { confirmed: true },
      })
    ).data,
  preview: async (data: SourceInput) =>
    (await apiClient.post<Preview>(`${base}/sources/preview`, data)).data,
  previewSource: async (source: string) =>
    (await apiClient.post<Preview>(`${base}/sources/${id(source)}/preview`))
      .data,
  protect: async (
    source: string,
    rules: ProtectedRule[],
    confirmations: string[],
    reason: string,
  ) =>
    (
      await apiClient.put(`${base}/sources/${id(source)}/protected`, {
        rules,
        confirm_patterns: confirmations,
        reason,
      })
    ).data,
  sync: async (sources: RepoSource[], mode: 'auto' | 'full') =>
    (
      await apiClient.post(`${base}/sources/sync-batch`, {
        source_ids: sources.map((s) => s.id),
        mode,
        confirmed_sources: Object.fromEntries(
          sources.map((s) => [s.id, s.config_hash]),
        ),
      })
    ).data,
  jobs: async (kb: string) =>
    (await apiClient.get<RepoJob[]>(`${base}/kbs/${id(kb)}/jobs`)).data,
  cancel: async (job: string) =>
    (await apiClient.delete(`${base}/jobs/${id(job)}`)).data,
  retry: async (job: string) =>
    (await apiClient.post(`${base}/jobs/${id(job)}/retry`)).data,
  build: async (kb: string) =>
    (await apiClient.post(`${base}/kbs/${id(kb)}/build`)).data,
  verify: async (kb: string) =>
    (
      await apiClient.get<VerificationReport>(
        `${base}/kbs/${id(kb)}/verify-exclusions`,
      )
    ).data,
  settings: async () =>
    (await apiClient.get<RepoSettings>(`${base}/settings/repo-kb`)).data,
  saveSettings: async (data: RepoSettings) =>
    (await apiClient.put<RepoSettings>(`${base}/settings/repo-kb`, data)).data,
  applyDefaults: async (
    sources: string[],
    confirmations: string[],
    reason: string,
  ) =>
    (
      await apiClient.post(`${base}/settings/repo-kb/apply-defaults`, {
        source_ids: sources,
        confirm_patterns: confirmations,
        reason,
      })
    ).data,
  folders: async (path?: string) =>
    (
      await apiClient.get<FolderListing>(`${base}/fs/browse`, {
        params: { path },
      })
    ).data,
  tree: async (kb: string) =>
    (
      await apiClient.get<{
        pages: WikiPage[]
        health: Record<string, number>
      }>(`${base}/kbs/${id(kb)}/tree`)
    ).data,
  page: async (kb: string, slug: string) =>
    (
      await apiClient.get<WikiPage>(
        `${base}/kbs/${id(kb)}/pages/${slug.split('/').map(id).join('/')}`,
      )
    ).data,
  cite: async (kb: string, ref: string) =>
    (
      await apiClient.get<CitationResult>(`${base}/kbs/${id(kb)}/cite`, {
        params: { ref },
      })
    ).data,
  search: async (kb: string, q: string, category?: string, module?: string) =>
    (
      await apiClient.get<SearchHit[]>(`${base}/kbs/${id(kb)}/search`, {
        params: { q, category, module },
      })
    ).data,
  discrepancies: async (kb: string) =>
    (await apiClient.get<Discrepancy[]>(`${base}/kbs/${id(kb)}/discrepancies`))
      .data,
  markDiscrepancy: async (
    kb: string,
    discrepancy: string,
    status: string,
    note: string,
  ) =>
    (
      await apiClient.patch(
        `${base}/kbs/${id(kb)}/discrepancies/${id(discrepancy)}`,
        { status, note },
      )
    ).data,
  revisions: async (kb: string, slug: string) =>
    (
      await apiClient.get<WikiRevision[]>(
        `${base}/kbs/${id(kb)}/pages/${slug}/revisions`,
      )
    ).data,
  revision: async (kb: string, slug: string, revision: number) =>
    (
      await apiClient.get<WikiRevision>(
        `${base}/kbs/${id(kb)}/pages/${slug}/revisions/${revision}`,
      )
    ).data,
  restore: async (kb: string, slug: string, revision: number) =>
    (
      await apiClient.post(`${base}/kbs/${id(kb)}/pages/${slug}/restore`, {
        revision,
      })
    ).data,
  addNote: async (kb: string, slug: string, body: string) =>
    (
      await apiClient.post(`${base}/kbs/${id(kb)}/pages/${slug}/notes`, {
        body,
      })
    ).data,
  deleteNote: async (kb: string, slug: string, note: string) =>
    (
      await apiClient.delete(
        `${base}/kbs/${id(kb)}/pages/${slug}/notes/${id(note)}`,
      )
    ).data,
  downloadZip: async (kb: string) => {
    const response = await apiClient.get(`${base}/kbs/${id(kb)}/export.zip`, {
      responseType: 'blob',
    })
    const url = URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = url
    a.download = 'wiki.zip'
    a.click()
    URL.revokeObjectURL(url)
  },
  staleModules: async () =>
    (await apiClient.get<StaleModule[]>(`${base}/rules/stale`)).data,
  compileBatch: async (
    items: { kb_id: string; modules?: string[]; flows?: string[] }[],
    model_id?: string,
  ) =>
    (
      await apiClient.post<{ batch_id: string }>(
        `${base}/rules/compile-batch`,
        { items, model_id },
      )
    ).data,
  batch: async (batch: string) =>
    (await apiClient.get<CompileBatch>(`${base}/rules/batches/${id(batch)}`))
      .data,
  cancelBatch: async (batch: string) =>
    (await apiClient.delete(`${base}/rules/batches/${id(batch)}`)).data,
  proposeFlows: async (kb: string, model_id?: string) =>
    (
      await apiClient.post<{ flows: FlowProposal[] }>(
        `${base}/kbs/${id(kb)}/compile-flows`,
        { model_id },
      )
    ).data,
  exportConfig: async (kb: string) =>
    (await apiClient.get<ExportConfig>(`${base}/kbs/${id(kb)}/export`)).data,
  saveExport: async (kb: string, config: ExportConfig) =>
    (await apiClient.put(`${base}/kbs/${id(kb)}/export`, config)).data,
  exportRun: async (kb: string) =>
    (await apiClient.post(`${base}/kbs/${id(kb)}/export/run`)).data,
  mounts: async (notebook: string) =>
    (await apiClient.get<RepoKB[]>(`${base}/notebooks/${id(notebook)}/mounts`))
      .data,
  setMounts: async (notebook: string, kb_ids: string[]) =>
    (
      await apiClient.put(`${base}/notebooks/${id(notebook)}/mounts`, {
        kb_ids,
      })
    ).data,
  saveAnswer: async (
    kb: string,
    session_id: string,
    message_id: string,
    title: string,
  ) =>
    (
      await apiClient.post(`${base}/kbs/${id(kb)}/qa-pages`, {
        session_id,
        message_id,
        title,
      })
    ).data,
  editKB: async (
    kb: string,
    data: Partial<RepoKB> & { detach_confirmed?: string[] },
  ) => (await apiClient.patch(`${base}/kbs/${id(kb)}`, data)).data,
  deleteKB: async (kb: string) =>
    (
      await apiClient.delete(`${base}/kbs/${id(kb)}`, {
        params: { confirmed: true },
      })
    ).data,
  citeNotebook: async (notebook: string, ref: string) =>
    (
      await apiClient.get<CitationResult>(
        `${base}/notebooks/${id(notebook)}/cite`,
        { params: { ref } },
      )
    ).data,
}
