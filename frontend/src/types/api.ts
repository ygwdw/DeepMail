// DeepMail 后端 API 的 TypeScript 类型定义
// 与 backend/app/schemas/*.py 和 backend/app/api/*.py 的返回结构对齐

export interface UserPublic {
  id: string
  username: string
  role: string
  is_active: boolean
}

export interface MeRead extends UserPublic {
  token_budget: number
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  expires_in: number
}

export interface EmailListItem {
  id: string
  message_id: string
  thread_id: string | null
  sender_name: string | null
  sender_email: string
  subject: string
  sent_at: string
  received_at: string
  is_read: boolean
  spam_score: number
  folder: string
  labels: string[]
  categories: string[]
  summary: string | null
  todos_extracted: Array<{ content: string; due_date?: string | null; priority?: string }>
  body_preview: string
}

export interface EmailRead extends EmailListItem {
  user_id: string
  recipients: string[]
  cc: string[]
  body_text: string
  entities_extracted: Array<{ name: string; type?: string }>
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface CategoryRead {
  id: string
  name: string
  description: string
  rules_json: Record<string, unknown>
  is_system: boolean
  is_spam_category: boolean
  count: number
}

export interface LabelRead {
  id: string
  name: string
  description: string
  color: string
  count: number
}

export interface TodoRead {
  id: string
  email_id: string | null
  content: string
  due_date: string | null
  priority: 'low' | 'medium' | 'high'
  status: 'pending' | 'done' | 'cancelled'
  created_at: string
}

// 邮件元数据里的 todo item（schema TodoItem 的 TS 镜像）
export interface EmailTodoItem {
  content: string
  due_date?: string | null
  priority?: 'low' | 'medium' | 'high'
}

export interface ChatSession {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool_calls: unknown[]
  created_at: string
}

export interface SendMessageResponse {
  trace_id: string
  user_message_id: string
  assistant_message_id: string
  final_response: string
  agents_invoked: string[]
  current_intent: string
  iterations: number
  memory_used: Record<string, unknown>
  compressed: boolean
  reasoning: string | null
}

export interface PersonaRead {
  profile_json: Record<string, unknown>
  updated_at: string
}

export interface TopicRead {
  id: string
  topic: string
  summary: string
  created_at: string
}

export interface EventRead {
  id: string
  title: string
  summary: string
  status: string
  confidence: number
  start_at: string | null
  end_at: string | null
  created_at: string
  updated_at: string
}

export interface TimelineRead {
  id: string
  occurred_at: string
  event_type: string
  content: string
  source_ref: string | null
}

export interface EventDetailRead extends EventRead {
  timeline: TimelineRead[]
}

export interface ClusterRunResult {
  events_created: number
  topics_used: number
}

export interface ClusterLastRun {
  last_run_at: string | null
}

export interface LongTermRead {
  id: string
  key: string
  value: Record<string, unknown>
  importance: number
  decay_score: number
  category: string
  updated_at: string
}

export interface KnowledgePartition {
  partition: string
  chunk_count: number
}

export interface KnowledgeHit {
  chunk_id: string
  content: string
  score: number
  partition: string
  source: string | null
  filename: string | null
  metadata: Record<string, unknown>
}

export interface KnowledgeSearchResponse {
  hits: KnowledgeHit[]
  total: number
}

export interface KnowledgeStats {
  total_chunks: number
  partitions: { partition: string; count: number }[]
}

// v2-M4.4: 上传结果扩展（zip 上传返回 files_indexed）
export interface KnowledgeUploadResponse {
  partition: string
  filename: string
  chunks_indexed: number
  files_indexed?: string[]  // zip 上传时包含
  kind?: 'file' | 'zip'
}

// v2-M4.4: L5 挂载检索 SSE 事件
export interface L5Source {
  partition: string
  source: string
  filename: string
  score: number
  chunk_id: string
}

export interface L5SourcesEvent {
  type: 'l5_sources'
  sources: L5Source[]
}