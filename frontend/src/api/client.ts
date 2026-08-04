// Axios 实例：Bearer token + 401 自动跳 /login
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'

export const TOKEN_KEY = 'deepmail_access_token'
export const REFRESH_KEY = 'deepmail_refresh_token'

export const api = axios.create({
  baseURL: '/api',
  timeout: 60_000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      // 过期 / 无效 → 清掉 token 跳 login
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_KEY)
      // 避免在 /login 页重复跳
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

export function getErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(String).join('; ')
    return err.message
  }
  if (err instanceof Error) return err.message
  return String(err)
}