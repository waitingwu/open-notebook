import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { repoKbApi } from '@/lib/api/repo-kb'
import { useTranslation } from './use-translation'
import axios from 'axios'

export function useRepoKBs() {
  return useQuery({
    queryKey: [...QUERY_KEYS.repoKb, 'list'],
    queryFn: () => repoKbApi.list(),
    retry: false,
  })
}
export function useRepoSources(kb: string) {
  return useQuery({
    queryKey: [...QUERY_KEYS.repoKb, kb, 'sources'],
    queryFn: () => repoKbApi.sources(kb),
    enabled: !!kb,
    retry: false,
    refetchInterval: 2000,
  })
}
export function useRepoJobs(kb: string) {
  return useQuery({
    queryKey: [...QUERY_KEYS.repoKb, kb, 'jobs'],
    queryFn: () => repoKbApi.jobs(kb),
    enabled: !!kb,
    retry: false,
    refetchInterval: 2000,
  })
}
export function useRepoSettings() {
  return useQuery({
    queryKey: [...QUERY_KEYS.repoKb, 'settings'],
    queryFn: repoKbApi.settings,
    retry: false,
  })
}
export function useRepoMutation<T>(mutationFn: (value: T) => Promise<unknown>) {
  const client = useQueryClient()
  const { t } = useTranslation()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: QUERY_KEYS.repoKb })
      toast.success(t('repoKb.saved'))
    },
    onError: (error: unknown) => {
      const detail = axios.isAxiosError(error)
        ? error.response?.data?.detail
        : undefined
      toast.error(
        typeof detail === 'string' ? detail : t('repoKb.failedRequest'),
      )
    },
  })
}
