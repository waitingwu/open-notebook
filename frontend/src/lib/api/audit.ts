import apiClient from './client'

export interface LocalCliStatus {
  provider: string
  display_name: string
  installed: boolean
  path?: string | null
  version?: string | null
  logged_in?: boolean | null
  auth_method?: string | null
  plan?: string | null
  error?: string | null
  suggested_models: string[]
  registered_models: { id: string; name: string }[]
}

export interface AuditRun {
  id: string
  provider: string
  model: string
  feature: string
  status: 'success' | 'error'
  failure_reason?: string | null
  runtime: 'local_cli' | 'api'
  started_at: string
  duration_ms?: number | null
  first_token_ms?: number | null
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  reasoning_tokens: number
  cost_usd_estimated?: number | null
  cost_usd_reported?: number | null
  notebook_id?: string | null
  source_ids?: string[]
}

export interface AuditRunEvent {
  seq: number
  type: string
  name: string
  detail: Record<string, unknown>
  created: string
}

export interface AuditRunDetail extends AuditRun {
  ended_at?: string
  prompt_chars?: number
  response_chars?: number
  prompt_sha256?: string
  cli_version?: string | null
  auth_mode?: string | null
  error_message?: string | null
  error_truncated?: boolean
  model_id?: string | null
  events: AuditRunEvent[]
  usage: {
    model: string
    input_tokens: number
    output_tokens: number
    cache_read_tokens: number
    cache_write_tokens: number
    reasoning_tokens: number
    cost_usd_reported?: number | null
  }[]
}

export interface UsageBucket {
  runs: number
  errors: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  reasoning_tokens: number
  cost_usd_estimated: number
  uncosted_runs: number
}

export interface UsageSummary {
  days: number
  totals: UsageBucket
  daily: (UsageBucket & { date: string })[]
  by_model: (UsageBucket & { key: string })[]
  by_feature: (UsageBucket & { key: string })[]
}

export interface RateLimitWindow {
  name: string
  used_percent?: number | null
  resets_at?: string | null
  status?: string | null
}

export interface RateLimitSnapshot {
  provider: string
  observed_at: string
  snapshot: {
    plan?: string | null
    status?: string | null
    windows: RateLimitWindow[]
    credits?: Record<string, unknown>
  }
}

export interface ModelRate {
  input: number
  output: number
  cache_read?: number | null
}

export interface AuditSettings {
  event_retention_days: number
  run_retention_days: number
  pricing: Record<string, ModelRate>
}

export interface RunFilters {
  limit?: number
  offset?: number
  provider?: string
  status?: string
  feature?: string
}

export const auditApi = {
  localCliStatus: async () =>
    (await apiClient.get<LocalCliStatus[]>('/local-cli/status')).data,
  registerLocalModel: async (provider: string, name: string) =>
    (await apiClient.post<{ id: string; created: boolean }>('/local-cli/models', { provider, name })).data,
  testModel: async (modelId: string) =>
    (await apiClient.post<{ success: boolean; message: string }>(`/models/${modelId}/test`)).data,
  runs: async (filters: RunFilters) =>
    (await apiClient.get<{ items: AuditRun[]; total: number }>('/audit/runs', { params: filters })).data,
  run: async (id: string) =>
    (await apiClient.get<AuditRunDetail>(`/audit/runs/${encodeURIComponent(id)}`)).data,
  usage: async (days: number) =>
    (await apiClient.get<UsageSummary>('/audit/usage', { params: { days } })).data,
  rateLimits: async () =>
    (await apiClient.get<RateLimitSnapshot[]>('/audit/rate-limits')).data,
  settings: async () =>
    (await apiClient.get<AuditSettings>('/audit/settings')).data,
  updateSettings: async (data: Partial<AuditSettings>) =>
    (await apiClient.put<AuditSettings>('/audit/settings', data)).data,
  applyRetention: async () =>
    (await apiClient.post<{ events_deleted: number; runs_deleted: number }>('/audit/retention/apply')).data,
  clearLogs: async () => (await apiClient.delete('/audit/logs')).data,
  exportRuns: async (format: 'csv' | 'json', days: number) =>
    (await apiClient.get<Blob>('/audit/export', { params: { format, days }, responseType: 'blob' })).data,
}
