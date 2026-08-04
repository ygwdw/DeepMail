import { api } from './client'
import type { EventDetailRead, EventRead, LongTermRead, TopicRead } from '@/types/api'

export const memoryApi = {
  // L2 topics
  async listTopics(days: number = 30, limit: number = 50): Promise<TopicRead[]> {
    const { data } = await api.get<TopicRead[]>('/memory/topics', { params: { days, limit } })
    return data
  },
  async deleteTopic(id: string): Promise<void> {
    await api.delete(`/memory/topics/${id}`)
  },
  // L3 events
  async listEvents(status?: string, limit: number = 50): Promise<EventRead[]> {
    const { data } = await api.get<EventRead[]>('/memory/events', { params: { status, limit } })
    return data
  },
  async getEvent(id: string): Promise<EventDetailRead> {
    const { data } = await api.get<EventDetailRead>(`/memory/events/${id}`)
    return data
  },
  async createEvent(payload: { title: string; summary?: string }): Promise<EventRead> {
    const { data } = await api.post<EventRead>('/memory/events', payload)
    return data
  },
  async deleteEvent(id: string): Promise<void> {
    await api.delete(`/memory/events/${id}`)
  },
  async extractEvents(days: number = 7, minTopics: number = 3): Promise<EventRead[]> {
    const { data } = await api.post<EventRead[]>('/memory/events/extract', null, {
      params: { days, min_topics: minTopics },
    })
    return data
  },
  // L4 long-term
  async listLongTerm(category?: string, minDecay: number = 0.1, limit: number = 50): Promise<LongTermRead[]> {
    const { data } = await api.get<LongTermRead[]>('/memory/long-term', {
      params: { category, min_decay: minDecay, limit },
    })
    return data
  },
  async runDecay(): Promise<{ updated: number }> {
    const { data } = await api.post<{ updated: number }>('/memory/long-term/decay')
    return data
  },
  async deleteLongTerm(key: string): Promise<void> {
    await api.delete(`/memory/long-term/${key}`)
  },
}