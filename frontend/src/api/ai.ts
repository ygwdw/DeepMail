// AI 技能路由（/api/emails/{id}/*）
import { api } from './client'

export interface ProcessSummary {
  email_id: string
  summary?: { content: string; confidence: number }
  todos?: { items: unknown[]; confidence: number }
  entities?: { items: unknown[]; confidence: number }
  categories?: { primary: string; confidence: number }
  spam?: { spam_score: number; is_spam: boolean; reasons: string[] }
  total_calls: number
  total_tokens?: number
  duration_ms?: number
}

export const aiApi = {
  async process(emailId: string): Promise<ProcessSummary> {
    const { data } = await api.post<ProcessSummary>(`/emails/${emailId}/process`)
    return data
  },
  async summary(emailId: string): Promise<{ output: { content: string; confidence: number } }> {
    const { data } = await api.post(`/emails/${emailId}/summary`)
    return data
  },
  async todos(emailId: string): Promise<{ output: { items: { content: string; due_date?: string | null; priority?: string }[]; confidence: number } }> {
    const { data } = await api.post(`/emails/${emailId}/todos`)
    return data
  },
  async classify(emailId: string): Promise<{ output: { primary: string; confidence: number } }> {
    const { data } = await api.post(`/emails/${emailId}/classify`)
    return data
  },
  async spam(emailId: string): Promise<{ output: { spam_score: number; is_spam: boolean; reasons: string[] } }> {
    const { data } = await api.post(`/emails/${emailId}/spam`)
    return data
  },
  async tagRecommend(emailId: string): Promise<{ existing_label_matches: unknown[]; recommended_new_labels: unknown[] }> {
    const { data } = await api.post(`/emails/${emailId}/tag/recommend`)
    return data
  },
  async entities(emailId: string): Promise<{ output: { items: unknown[]; confidence: number } }> {
    const { data } = await api.post(`/emails/${emailId}/entities`)
    return data
  },
}