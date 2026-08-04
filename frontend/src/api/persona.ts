import { api } from './client'
import type { PersonaRead } from '@/types/api'

export const personaApi = {
  async get(): Promise<PersonaRead> {
    const { data } = await api.get<PersonaRead>('/persona')
    return data
  },
  async patch(fields: Record<string, unknown>): Promise<PersonaRead> {
    const { data } = await api.patch<PersonaRead>('/persona', fields)
    return data
  },
  async clear(): Promise<void> {
    await api.delete('/persona')
  },
  async rollback(): Promise<PersonaRead> {
    const { data } = await api.post<PersonaRead>('/persona/rollback')
    return data
  },
}