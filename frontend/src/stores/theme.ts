// 主题切换：light / dark；存 localStorage
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { darkTheme } from 'naive-ui'
import type { GlobalTheme } from 'naive-ui'

const KEY = 'deepmail_theme'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref<boolean>(localStorage.getItem(KEY) === 'dark')

  watch(isDark, (v) => {
    localStorage.setItem(KEY, v ? 'dark' : 'light')
  })

  function toggle(): void {
    isDark.value = !isDark.value
  }

  const naiveTheme = computed<GlobalTheme | null>(() => (isDark.value ? darkTheme : null))

  return { isDark, toggle, naiveTheme }
})