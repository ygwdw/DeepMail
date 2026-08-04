<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  NCard, NSpace, NButton, NInput, NSelect, NSpin, useMessage, NScrollbar, NDivider,
} from 'naive-ui'
import { chatApi } from '@/api/chat'
import { getErrorMessage } from '@/api/client'
import type { ChatMessage, ChatSession, SendMessageResponse } from '@/types/api'
import ChatBubble from '@/components/ChatBubble.vue'
import EmptyState from '@/components/EmptyState.vue'

const props = defineProps<{ sessionId?: string }>()
const router = useRouter()
const route = useRoute()
const message = useMessage()

const sessions = ref<ChatSession[]>([])
const currentId = ref<string | null>(props.sessionId || null)
const messages = ref<ChatMessage[]>([])
const input = ref('')
const sending = ref(false)
const streaming = ref(false)
const streamingContent = ref('')
const lastAgents = ref<string[]>([])
const lastIntent = ref<string>('')
const scrollRef = ref<InstanceType<typeof NScrollbar> | null>(null)

async function loadSessions(): Promise<void> {
  sessions.value = await chatApi.listSessions()
  if (!currentId.value && sessions.value.length > 0) {
    currentId.value = sessions.value[0].id
  }
}

async function loadMessages(): Promise<void> {
  if (!currentId.value) {
    messages.value = []
    return
  }
  try {
    messages.value = await chatApi.listMessages(currentId.value)
    await nextTick()
    scrollToBottom()
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

async function newSession(): Promise<void> {
  const s = await chatApi.createSession('')
  sessions.value = [s, ...sessions.value]
  currentId.value = s.id
  messages.value = []
  router.replace({ name: 'chat', params: { sessionId: s.id } })
}

async function selectSession(id: string): Promise<void> {
  currentId.value = id
  router.replace({ name: 'chat', params: { sessionId: id } })
  await loadMessages()
}

async function deleteSession(id: string): Promise<void> {
  await chatApi.deleteSession(id)
  sessions.value = sessions.value.filter((s) => s.id !== id)
  if (currentId.value === id) {
    currentId.value = sessions.value[0]?.id || null
    await loadMessages()
  }
}

async function send(): Promise<void> {
  const content = input.value.trim()
  if (!content || sending.value) return

  let sid = currentId.value
  if (!sid) {
    const s = await chatApi.createSession(content.slice(0, 30))
    sessions.value = [s, ...sessions.value]
    sid = s.id
    currentId.value = sid
    router.replace({ name: 'chat', params: { sessionId: sid } })
  }

  // 立即 push 用户消息
  messages.value.push({
    id: 'tmp-' + Date.now(),
    role: 'user',
    content,
    tool_calls: [],
    created_at: new Date().toISOString(),
  })
  input.value = ''
  await nextTick()
  scrollToBottom()

  sending.value = true
  streaming.value = true
  streamingContent.value = ''
  try {
    const resp: SendMessageResponse = await chatApi.sendMessage(sid, content)
    streamingContent.value = resp.final_response
    lastAgents.value = resp.agents_invoked
    lastIntent.value = resp.current_intent
    // 拉一次完整消息
    await loadMessages()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    sending.value = false
    streaming.value = false
    streamingContent.value = ''
  }
}

function scrollToBottom(): void {
  // Naive UI NScrollbar 实例暴露 scrollTo(top) / scrollTo({ top, left, behavior })
  scrollRef.value?.scrollTo({ top: 999_999, behavior: 'smooth' })
}

watch(currentId, () => loadMessages())

onMounted(async () => {
  await loadSessions()
  await loadMessages()
  // 处理 query.first（新会话种子）
  const first = route.query.first as string | undefined
  if (first && props.sessionId) {
    input.value = first
    await send()
  }
})
</script>

<template>
  <div class="chat-layout">
    <NCard class="session-list" title="会话">
      <NSpace vertical>
        <NButton type="primary" block @click="newSession">+ 新会话</NButton>
        <NSelect
          :value="currentId"
          :options="sessions.map((s) => ({ label: s.title || '新会话', value: s.id }))"
          placeholder="选择会话"
          @update:value="selectSession"
        />
        <div v-if="currentId" class="delete">
          <NButton size="tiny" type="error" ghost @click="deleteSession(currentId)">删除当前</NButton>
        </div>
      </NSpace>
    </NCard>

    <NCard class="chat-main">
      <template #header>{{ currentId ? (sessions.find((s) => s.id === currentId)?.title || '对话') : '新对话' }}</template>

      <NScrollbar ref="scrollRef" class="scroll">
        <EmptyState v-if="messages.length === 0 && !streaming" description="开始对话吧" />
        <ChatBubble v-for="m in messages" :key="m.id" :message="m" />
        <ChatBubble
          v-if="streaming"
          :message="{ id: 'stream', role: 'assistant', content: streamingContent, tool_calls: [], created_at: new Date().toISOString() }"
          :streaming="true"
        />
        <NSpin v-if="sending && !streaming" size="small" />
      </NScrollbar>

      <NDivider style="margin: 12px 0" />

      <div v-if="lastAgents.length" class="muted meta">
        调用的 Agent：{{ lastAgents.join(', ') }} ｜ Intent：{{ lastIntent }}
      </div>

      <NSpace align="center" :wrap="false">
        <NInput
          v-model:value="input"
          type="textarea"
          :rows="2"
          placeholder="输入消息..."
          :disabled="sending"
          @keydown.enter.exact.prevent="send"
        />
        <NButton type="primary" :loading="sending" @click="send">发送</NButton>
      </NSpace>
    </NCard>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  gap: 12px;
  height: 100%;
}
.session-list {
  width: 220px;
  flex-shrink: 0;
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.scroll {
  height: calc(100vh - 280px);
  padding: 12px;
}
.delete {
  margin-top: 8px;
}
.meta {
  margin-bottom: 8px;
  font-size: 12px;
}
</style>