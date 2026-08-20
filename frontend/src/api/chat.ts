import { api } from './client'
import type { ChatMessage, ChatSession, L5Source, SendMessageResponse } from '@/types/api'

export interface StreamEvent {
  type: 'user' | 'thinking' | 'tool_start' | 'tool_end' | 'content' | 'content_replace' | 'l5_sources' | 'usage' | 'error' | 'end'
  // 通用
  delta?: string
  text?: string  // content_replace 用
  message?: string
  // tool_start / tool_end / thinking 来源节点名（v2-M8.11 thinking 分段用）
  name?: string
  args_summary?: string
  summary?: string
  // v2-M4.4 L5 溯源
  sources?: L5Source[]
  // usage
  duration_ms?: number
  iterations?: number
  tools_called?: number
  tokens?: number
  input_tokens?: number
  output_tokens?: number
  agents_invoked?: string[]
  compressed?: boolean
  // user
  content?: string
  user_message_id?: string
  assistant_message_id?: string
  final_response?: string
}

// v2-M4.4: 发送消息选项（enable_l5 + partitions）
export interface SendMessageOptions {
  enable_l5?: boolean
  enable_l5_partitions?: string[]
}

export const chatApi = {
  async listSessions(): Promise<ChatSession[]> {
    const { data } = await api.get<ChatSession[]>('/chat/sessions')
    return data
  },
  async createSession(title: string = ''): Promise<ChatSession> {
    const { data } = await api.post<ChatSession>('/chat/sessions', { title })
    return data
  },
  async createDraftReplySession(emailId: string): Promise<ChatSession> {
    const { data } = await api.post<ChatSession>('/chat/sessions/draft-reply', null, {
      params: { email_id: emailId },
    })
    return data
  },
  async deleteSession(id: string): Promise<void> {
    await api.delete(`/chat/sessions/${id}`)
  },
  async listMessages(sessionId: string): Promise<ChatMessage[]> {
    const { data } = await api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`)
    return data
  },
  async sendMessage(
    sessionId: string,
    content: string,
    options: SendMessageOptions = {},
  ): Promise<SendMessageResponse> {
    const { data } = await api.post<SendMessageResponse>(
      `/chat/sessions/${sessionId}/messages`,
      {
        content,
        enable_l5: options.enable_l5 ?? false,
        enable_l5_partitions: options.enable_l5_partitions ?? [],
      },
    )
    return data
  },
  /**
   * v2-M8：SSE 流式发送。onEvent 回调每次收到一个事件；返回 Promise 在收到 'end' 事件后 resolve。
   * v2-M4.4：支持 L5 挂载检索（enable_l5 + enable_l5_partitions）。
   */
  async sendMessageStream(
    sessionId: string,
    content: string,
    onEvent: (ev: StreamEvent) => void,
    options: SendMessageOptions = {},
  ): Promise<void> {
    const token = localStorage.getItem('deepmail_access_token')
    const res = await fetch(`/api/chat/sessions/${sessionId}/messages/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        content,
        enable_l5: options.enable_l5 ?? false,
        enable_l5_partitions: options.enable_l5_partitions ?? [],
      }),
    })
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '')
      throw new Error(`stream failed: ${res.status} ${text}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let finished = false
    while (!finished) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      // SSE 格式：多行 `data: ...\n\n`
      let idx: number
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const chunk = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        for (const line of chunk.split('\n')) {
          if (line.startsWith('data: ')) {
            try {
              const ev = JSON.parse(line.slice(6)) as StreamEvent
              onEvent(ev)
              if (ev.type === 'end') finished = true
            } catch {
              // 忽略无法解析的行
            }
          }
        }
      }
    }
  },
}