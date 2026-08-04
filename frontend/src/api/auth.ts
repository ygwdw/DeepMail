import { api, REFRESH_KEY, TOKEN_KEY } from './client'
import type { TokenPair } from '@/types/api'

export interface LoginPayload {
  username: string
  password: string
}

export const authApi = {
  async login(payload: LoginPayload): Promise<TokenPair> {
    const { data } = await api.post<TokenPair>('/auth/login', payload)
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(REFRESH_KEY, data.refresh_token)
    return data
  },
  async refresh(): Promise<TokenPair> {
    const refresh = localStorage.getItem(REFRESH_KEY)
    if (!refresh) throw new Error('no refresh token')
    const { data } = await api.post<TokenPair>('/auth/refresh', { refresh_token: refresh })
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(REFRESH_KEY, data.refresh_token)
    return data
  },
  logout(): void {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}