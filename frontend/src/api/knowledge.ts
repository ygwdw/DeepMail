import { api } from './client'
import type {
  KnowledgePartition,
  KnowledgeSearchResponse,
  KnowledgeStats,
  KnowledgeUploadResponse,
} from '@/types/api'

export const knowledgeApi = {
  async listPartitions(): Promise<KnowledgePartition[]> {
    const { data } = await api.get<KnowledgePartition[]>('/knowledge/partitions')
    return data
  },
  async deletePartition(name: string): Promise<void> {
    await api.delete(`/knowledge/partitions/${name}`)
  },
  // v2-M4.4: 重命名分区
  async renamePartition(oldName: string, newName: string): Promise<{ renamed_chunks: number; old_name: string; new_name: string }> {
    const { data } = await api.post('/knowledge/partitions/rename', {
      old_name: oldName,
      new_name: newName,
    })
    return data
  },
  async upload(partition: string, file: File): Promise<KnowledgeUploadResponse> {
    const form = new FormData()
    form.append('partition', partition)
    form.append('file', file)
    const { data } = await api.post<KnowledgeUploadResponse>('/knowledge/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },
  async indexEmails(limit: number = 1000): Promise<{ chunks_indexed: number }> {
    const { data } = await api.post('/knowledge/index/emails', null, { params: { limit } })
    return data
  },
  async search(payload: { query: string; partition?: string; top_k?: number; use_rerank?: boolean }): Promise<KnowledgeSearchResponse> {
    const { data } = await api.post<KnowledgeSearchResponse>('/knowledge/search', payload)
    return data
  },
  async stats(): Promise<KnowledgeStats> {
    const { data } = await api.get<KnowledgeStats>('/knowledge/stats')
    return data
  },
}