// AI 技能路由（/api/emails/{id}/*）
// 类型与 backend/app/agents/schemas.py 一一对应
import { api } from './client'

// SummaryOutput: { summary: string; key_points: string[] }
export interface SummaryResp {
  output: { summary: string; key_points: string[] }
}

// TodoExtractOutput: v2-M4.2 wrapper class { items: TodoItem[] }
export interface TodoItem {
  content: string
  due_date?: string | null
  priority?: 'low' | 'medium' | 'high'
}
export interface TodoResp {
  output: { items: TodoItem[] } | TodoItem[]
}

// helper：兼容 wrapper / 裸 list 两种响应
export function unwrapTodoOutput(resp: TodoResp): TodoItem[] {
  const out = resp.output
  if (Array.isArray(out)) return out
  if (out && Array.isArray((out as { items?: TodoItem[] }).items)) {
    return (out as { items: TodoItem[] }).items
  }
  return []
}

// EntityExtractOutput: { entities, relations }
export interface EntityItem {
  name: string
  type: string
}
export interface RelationItem {
  subject: string
  predicate: string
  object: string
}
export interface EntityResp {
  output: { entities: EntityItem[]; relations: RelationItem[] }
}

// ClassifyOutput: { category_name, confidence }
export interface ClassifyResp {
  output: { category_name: string; confidence: number }
}

// SpamOutput: { spam_score, is_spam, reasons }
export interface SpamResp {
  output: { spam_score: number; is_spam: boolean; reasons: string[] }
}

// TagRecommendOutput: { existing_label_matches, recommended_new_labels }
export interface TagRecommendResp {
  output: {
    existing_label_matches: Array<{ name: string; confidence: number }>
    recommended_new_labels: Array<{ name: string; type: string; reason: string }>
  }
}

export const aiApi = {
  async process(emailId: string): Promise<unknown> {
    const { data } = await api.post(`/emails/${emailId}/process`)
    return data
  },
  async summary(emailId: string): Promise<SummaryResp> {
    const { data } = await api.post<SummaryResp>(`/emails/${emailId}/summary`)
    return data
  },
  async todos(emailId: string): Promise<TodoResp> {
    const { data } = await api.post<TodoResp>(`/emails/${emailId}/todos`)
    return data
  },
  async classify(emailId: string): Promise<ClassifyResp> {
    const { data } = await api.post<ClassifyResp>(`/emails/${emailId}/classify`)
    return data
  },
  async spam(emailId: string): Promise<SpamResp> {
    const { data } = await api.post<SpamResp>(`/emails/${emailId}/spam`)
    return data
  },
  async tagRecommend(emailId: string): Promise<TagRecommendResp> {
    const { data } = await api.post<TagRecommendResp>(`/emails/${emailId}/tag/recommend`)
    return data
  },
  async entities(emailId: string): Promise<EntityResp> {
    const { data } = await api.post<EntityResp>(`/emails/${emailId}/entities`)
    return data
  },
}