<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NSpin, NButton, NTag, NScrollbar, useMessage } from 'naive-ui'
import { emailsApi } from '@/api/emails'
import { aiApi, unwrapTodoOutput } from '@/api/ai'
import { getErrorMessage } from '@/api/client'
import type { EmailRead, EmailTodoItem } from '@/types/api'
import EmailMetaCard from '@/components/EmailMetaCard.vue'
import SummaryCard from '@/components/SummaryCard.vue'
import TodoCard from '@/components/TodoCard.vue'
import BodyCard from '@/components/BodyCard.vue'

const props = defineProps<{ id: string }>()
const router = useRouter()
const message = useMessage()

const email = ref<EmailRead | null>(null)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    email.value = await emailsApi.detail(props.id)
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

async function regenSummary(): Promise<void> {
  if (!email.value) return
  try {
    const r = await aiApi.summary(email.value.id)
    if (email.value) email.value.summary = r.output.summary
    message.success('摘要已重新生成')
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

async function regenAll(): Promise<void> {
  if (!email.value) return
  try {
    await Promise.all([
      aiApi.summary(email.value.id).then((r) => { if (email.value) email.value.summary = r.output.summary }),
      aiApi.todos(email.value.id).then((r) => { if (email.value) email.value.todos_extracted = unwrapTodoOutput(r) }),
      aiApi.classify(email.value.id).then((r) => { if (email.value) email.value.categories = [r.output.category_name] }),
    ])
    message.success('已重新生成')
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

function reply(): void {
  if (!email.value) return
  router.push({ name: 'compose', query: { reply_to: email.value.id } })
}

async function autoFillMissingAI(): Promise<void> {
  if (!email.value) return
  const e = email.value
  const tasks: Array<Promise<void>> = []
  if (!e.summary) {
    tasks.push(
      aiApi.summary(e.id)
        .then((r) => { if (email.value) email.value.summary = r.output.summary })
        .catch(() => {}),
    )
  }
  if (!e.categories || e.categories.length === 0) {
    tasks.push(
      aiApi.classify(e.id)
        .then((r) => { if (email.value) email.value.categories = [r.output.category_name] })
        .catch(() => {}),
    )
  }
  tasks.push(
    aiApi.todos(e.id)
      .then((r) => { if (email.value) email.value.todos_extracted = unwrapTodoOutput(r) })
      .catch(() => {}),
  )
  void Promise.allSettled(tasks)
}

onMounted(async () => {
  await load()
  await autoFillMissingAI()
})
</script>

<template>
  <NSpin :show="loading">
    <div v-if="email" class="detail-container">
      <div class="detail-header">
        <NButton text @click="router.back()">← 返回</NButton>
        <NButton type="primary" @click="reply">📧 回信</NButton>
        <NButton @click="regenAll">🔄 重新摘要</NButton>
        <NTag v-if="email.folder === 'spam'" type="error" :bordered="false">垃圾</NTag>
      </div>
      <h1 class="subject">{{ email.subject || '(无主题)' }}</h1>

      <NScrollbar class="scroll-area">
        <EmailMetaCard :email="email" />
        <SummaryCard :summary="email.summary" />
        <div class="divider"></div>
        <TodoCard :todos="(email.todos_extracted || []) as EmailTodoItem[]" />
        <div class="divider"></div>
        <BodyCard :body="email.body_text" />
      </NScrollbar>
    </div>
  </NSpin>
</template>

<style scoped>
.detail-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  margin: -16px;
  overflow: hidden;
}
.detail-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--n-divider-color);
  background: var(--n-card-color);
  flex-shrink: 0;
}
.subject {
  font-size: 20px;
  font-weight: 600;
  margin: 12px 20px 8px 20px;
  color: var(--n-text-color-1);
  line-height: 1.4;
  flex-shrink: 0;
}
.scroll-area {
  flex: 1;
  padding: 0 20px 20px 20px;
}
.divider {
  height: 2px;
  background: linear-gradient(to right, transparent, var(--n-divider-color) 20%, var(--n-divider-color) 80%, transparent);
  margin: 14px 0;
  width: 100%;
  flex-shrink: 0;
}
</style>