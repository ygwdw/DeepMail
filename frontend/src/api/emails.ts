import { api } from './client'
import type { EmailListItem, EmailRead, Page } from '@/types/api'

export const emailsApi = {
  async list(params: { limit?: number; offset?: number; folder?: string; sync?: boolean } = {}): Promise<Page<EmailListItem>> {
    const { data } = await api.get<Page<EmailListItem>>('/emails', { params })
    return data
  },
  async detail(id: string): Promise<EmailRead> {
    const { data } = await api.get<EmailRead>(`/emails/${id}`)
    return data
  },
  async sync(): Promise<{ added: number; total: number }> {
    const { data } = await api.post<{ added: number; total: number }>('/emails/sync')
    return data
  },
  async draft(
    id: string,
    payload: { instruction: string; tone?: 'auto' | 'formal' | 'casual' },
  ): Promise<{ output: { draft_text: string; confidence: number; tone: string } }> {
    const { data } = await api.post(`/emails/${id}/draft`, payload)
    return data
  },
}