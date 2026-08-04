import { api } from './client'
import type { MeRead } from '@/types/api'

export const meApi = {
  async get(): Promise<MeRead> {
    const { data } = await api.get<MeRead>('/me')
    return data
  },
  async patchTokenBudget(tokenBudget: number): Promise<MeRead> {
    const { data } = await api.patch<MeRead>('/me', { token_budget: tokenBudget })
    return data
  },
}