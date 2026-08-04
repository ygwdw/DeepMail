import { api } from './client'
import type { ChatMessage, ChatSession, SendMessageResponse } from '@/types/api'

export const chatApi = {
  async listSessions(): Promise<ChatSession[]> {
    const { data } = await api.get<ChatSession[]>('/chat/sessions')
    return data
  },
  async createSession(title: string = ''): Promise<ChatSession> {
    const { data } = await api.post<ChatSession>('/chat/sessions', { title })
    return data
  },
  async deleteSession(id: string): Promise<void> {
    await api.delete(`/chat/sessions/${id}`)
  },
  async listMessages(sessionId: string): Promise<ChatMessage[]> {
    const { data } = await api.get<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`)
    return data
  },
  async sendMessage(sessionId: string, content: string): Promise<SendMessageResponse> {
    const { data } = await api.post<SendMessageResponse>(`/chat/sessions/${sessionId}/messages`, { content })
    return data
  },
}