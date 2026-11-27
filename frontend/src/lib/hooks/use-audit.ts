import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { auditApi, AuditSettings, RunFilters } from '@/lib/api/audit'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorMessage } from '@/lib/utils/error-handler'

export const AUDIT_KEYS = {
  all: ['audit'] as const,
  localCli: ['audit', 'local-cli'] as const,
  runs: (filters: RunFilters) => ['audit', 'runs', filters] as const,
  run: (id: string) => ['audit', 'run', id] as const,
  usage: (days: number) => ['audit', 'usage', days] as const,
  rateLimits: ['audit', 'rate-limits'] as const,
  settings: ['audit', 'settings'] as const,
}

function useErrorToast() {
  const { toast } = useToast()
  const { t } = useTranslation()
  return (error: unknown) =>
    toast({
      title: t('common.error'),
      description: getApiErrorMessage(error, (key) => t(key), 'common.error'),
      variant: 'destructive',
    })
}

export function useLocalCliStatus() {
  return useQuery({ queryKey: AUDIT_KEYS.localCli, queryFn: auditApi.localCliStatus })
}

export function useRegisterLocalModel() {
  const queryClient = useQueryClient()
  const onError = useErrorToast()
  return useMutation({
    mutationFn: ({ provider, name }: { provider: string; name: string }) =>
      auditApi.registerLocalModel(provider, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: AUDIT_KEYS.localCli })
      queryClient.invalidateQueries({ queryKey: ['models'] })
    },
    onError,
  })
}

export function useTestLocalModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (modelId: string) => auditApi.testModel(modelId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: AUDIT_KEYS.all }),
  })
}

export function useAuditRuns(filters: RunFilters) {
  return useQuery({ queryKey: AUDIT_KEYS.runs(filters), queryFn: () => auditApi.runs(filters) })
}

export function useAuditRun(id: string | null) {
  return useQuery({
    queryKey: AUDIT_KEYS.run(id ?? ''),
    queryFn: () => auditApi.run(id as string),
    enabled: !!id,
  })
}

export function useUsageSummary(days: number) {
  return useQuery({ queryKey: AUDIT_KEYS.usage(days), queryFn: () => auditApi.usage(days) })
}

export function useRateLimits() {
  return useQuery({ queryKey: AUDIT_KEYS.rateLimits, queryFn: auditApi.rateLimits })
}

export function useAuditSettings() {
  return useQuery({ queryKey: AUDIT_KEYS.settings, queryFn: auditApi.settings })
}

export function useUpdateAuditSettings() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const onError = useErrorToast()
  return useMutation({
    mutationFn: (data: Partial<AuditSettings>) => auditApi.updateSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: AUDIT_KEYS.all })
      toast({ title: t('common.success'), description: t('common.saveSuccess') })
    },
    onError,
  })
}

export function useApplyRetention() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const onError = useErrorToast()
  return useMutation({
    mutationFn: auditApi.applyRetention,
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: AUDIT_KEYS.all })
      toast({
        title: t('common.success'),
        description: t('aiAudit.retentionApplied', {
          events: r.events_deleted,
          runs: r.runs_deleted,
        }),
      })
    },
    onError,
  })
}

export function useClearAuditLogs() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()
  const onError = useErrorToast()
  return useMutation({
    mutationFn: auditApi.clearLogs,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: AUDIT_KEYS.all })
      toast({ title: t('common.success'), description: t('aiAudit.cleared') })
    },
    onError,
  })
}
