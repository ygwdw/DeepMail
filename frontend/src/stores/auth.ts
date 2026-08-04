// 鉴权状态：token + 用户信息
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'
import { meApi } from '@/api/me'
import { TOKEN_KEY } from '@/api/client'
import type { MeRead } from '@/types/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<MeRead | null>(null)
  const isAuthed = ref<boolean>(Boolean(localStorage.getItem(TOKEN_KEY)))

  async function login(username: string, password: string): Promise<void> {
    await authApi.login({ username, password })
    isAuthed.value = true
    await fetchMe()
  }

  async function fetchMe(): Promise<MeRead | null> {
    if (!isAuthed.value) return null
    try {
      user.value = await meApi.get()
    } catch {
      logout()
    }
    return user.value
  }

  function logout(): void {
    authApi.logout()
    isAuthed.value = false
    user.value = null
  }

  return { user, isAuthed, login, logout, fetchMe }
})