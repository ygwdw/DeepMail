<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NLayout, NLayoutHeader, NLayoutSider, NLayoutContent,
  NMenu, NIcon, NSpace, NButton, NAvatar, NDropdown, useMessage,
} from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { h } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const themeStore = useThemeStore()
const message = useMessage()

function renderIcon(icon: string) {
  return () => h('span', { class: 'iconify', style: 'font-size:16px' }, icon)
}

const menuOptions: MenuOption[] = [
  { label: '收件箱', key: '/inbox', icon: renderIcon('📧') },
  { label: '会话', key: '/chat', icon: renderIcon('💬') },
  { label: '待办', key: '/todos', icon: renderIcon('📋') },
  { label: '日报', key: '/digest', icon: renderIcon('📊') },
  { label: '记忆', key: '/memory', icon: renderIcon('🧠') },
  { label: '人格', key: '/persona', icon: renderIcon('👤') },
  { label: '知识库', key: '/knowledge', icon: renderIcon('📚') },
  { label: '设置', key: '/settings', icon: renderIcon('⚙️') },
]

const activeKey = computed(() => {
  // 匹配最长前缀
  const keys = menuOptions.map((m) => String(m.key)).sort((a, b) => b.length - a.length)
  for (const k of keys) {
    if (route.path === k || route.path.startsWith(k + '/')) return k
  }
  return '/inbox'
})

function onMenuSelect(key: string): void {
  router.push(key)
}

const userMenu = computed(() => [
  { label: themeStore.isDark ? '🌞 浅色模式' : '🌙 深色模式', key: 'theme' },
  { label: '退出登录', key: 'logout' },
])

function onUserSelect(key: string): void {
  if (key === 'theme') themeStore.toggle()
  else if (key === 'logout') {
    auth.logout()
    message.info('已退出')
    router.push('/login')
  }
}

const username = computed(() => auth.user?.username || '...')
</script>

<template>
  <NLayout has-sider style="height: 100vh">
    <NLayoutSider
      bordered
      :collapsed-width="64"
      :width="200"
      show-trigger
      collapse-mode="width"
    >
      <div class="logo">
        <span class="logo-icon">📬</span>
        <span class="logo-text">DeepMail</span>
      </div>
      <NMenu
        :options="menuOptions"
        :value="activeKey"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        @update:value="onMenuSelect"
      />
    </NLayoutSider>
    <NLayout>
      <NLayoutHeader bordered class="header">
        <div class="title">{{ menuOptions.find((m) => m.key === activeKey)?.label }}</div>
        <NSpace align="center">
          <NButton text @click="themeStore.toggle()">
            {{ themeStore.isDark ? '🌞' : '🌙' }}
          </NButton>
          <NDropdown :options="userMenu" trigger="click" @select="onUserSelect">
            <NSpace align="center" style="cursor: pointer">
              <NAvatar round size="small" style="background: var(--n-primary-color)">
                {{ username.charAt(0).toUpperCase() }}
              </NAvatar>
              <span>{{ username }}</span>
            </NSpace>
          </NDropdown>
        </NSpace>
      </NLayoutHeader>
      <NLayoutContent class="content">
        <RouterView />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>

<style scoped>
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  font-size: 18px;
  font-weight: 600;
}
.logo-icon { font-size: 22px; }
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  height: 56px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.content {
  padding: 16px;
  height: calc(100vh - 56px);
  overflow: hidden;
  position: relative;
}
</style>