<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NButton, useMessage, NScrollbar } from 'naive-ui'
import { chatApi } from '@/api/chat'
import { getErrorMessage } from '@/api/client'
import type { ChatSession } from '@/types/api'
import ChatPanel from '@/components/ChatPanel.vue'
import EmptyState from '@/components/EmptyState.vue'

const router = useRouter()
const route = useRoute()
const message = useMessage()

const sessions = ref<ChatSession[]>([])
const currentId = ref<string | null>((route.params.sessionId as string) || null)
const loading = ref(false)

async function loadSessions(): Promise<void> {
  try {
    sessions.value = await chatApi.listSessions()
    if (!currentId.value && sessions.value.length > 0) {
      currentId.value = sessions.value[0].id
    }
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

async function newSession(): Promise<void> {
  try {
    const s = await chatApi.createSession('')
    sessions.value = [s, ...sessions.value]
    currentId.value = s.id
    router.replace({ name: 'chat', params: { sessionId: s.id } })
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

function selectSession(id: string): void {
  currentId.value = id
  router.replace({ name: 'chat', params: { sessionId: id } })
}

async function deleteSession(id: string, e: MouseEvent): Promise<void> {
  e.stopPropagation()
  try {
    await chatApi.deleteSession(id)
    sessions.value = sessions.value.filter((s) => s.id !== id)
    if (currentId.value === id) {
      currentId.value = sessions.value[0]?.id || null
      router.replace({ name: 'chat', params: { sessionId: currentId.value || '' } })
    }
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

watch(
  () => route.params.sessionId,
  (v) => {
    if (typeof v === 'string') currentId.value = v
  },
)

onMounted(loadSessions)
</script>

<template>
  <div class="chat-layout">
    <!-- 左侧：会话列表 -->
    <div class="session-pane">
      <div class="session-header">
        <NButton size="small" type="primary" @click="newSession">+ 新会话</NButton>
      </div>
      <NScrollbar class="session-scroll">
        <div v-if="loading && sessions.length === 0" class="loading muted">加载中...</div>
        <EmptyState v-else-if="sessions.length === 0" description="还没有会话">
          <NButton @click="newSession">+ 创建一个</NButton>
        </EmptyState>
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: currentId === s.id }"
          @click="selectSession(s.id)"
        >
          <div class="session-content">
            <span class="session-name truncate">{{ s.title || '新会话' }}</span>
            <NButton
              size="tiny"
              text
              type="error"
              class="delete-btn"
              @click="(e) => deleteSession(s.id, e)"
            >×</NButton>
          </div>
        </div>
      </NScrollbar>
    </div>

    <!-- 右侧：聊天面板（占满整列） -->
    <div class="chat-main">
      <ChatPanel v-if="currentId" :key="currentId" :session-id="currentId" />
      <EmptyState v-else description="左侧选择或新建一个会话" />
    </div>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  gap: 12px;
  height: 100%;
  width: 100%;
  overflow: hidden;
  position: relative;
}
.session-pane {
  width: 260px;
  flex-shrink: 0;
  background: var(--n-card-color);
  border: 1px solid var(--n-divider-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}
.session-header {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--n-divider-color);
  background: var(--n-hover-color);
  flex-shrink: 0;
}
.session-header .title {
  font-size: 13px;
  font-weight: 600;
}
.session-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.loading {
  padding: 16px;
  font-size: 12px;
}
.session-item {
  padding: 10px 14px;
  cursor: pointer;
  border-bottom: 1px solid var(--n-divider-color);
  transition: background 0.15s;
}
.session-item:hover {
  background: var(--n-hover-color);
}
.session-item.active {
  background: var(--n-primary-color-hover);
}
.session-item.active .session-name {
  color: var(--n-primary-color);
  font-weight: 600;
}
.session-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.session-name {
  font-size: 13px;
  flex: 1;
}
.delete-btn {
  visibility: hidden;
}
.session-item:hover .delete-btn {
  visibility: visible;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  min-width: 0;
  position: relative;
}
.chat-main > * {
  flex: 1;
  min-height: 0;
}
</style>