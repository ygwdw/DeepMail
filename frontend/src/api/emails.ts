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
  // v2-M12: 批量重新分类/打标
  async reclassify(emailIds: string[], doTag = true): Promise<{ processed: number; failed: Array<{ email_id: string; error: string }> }> {
    const { data } = await api.post('/emails/reclassify', { email_ids: emailIds, do_tag: doTag })
    return data
  },
  // v2-M12: 发送邮件（真实 SMTP）
  async send(payload: { to: string[]; cc?: string[]; subject: string; body_text: string; body_html?: string }): Promise<{ sent: boolean; email_id: string; folder: string }> {
    const { data } = await api.post('/emails/send', payload)
    return data
  },
}