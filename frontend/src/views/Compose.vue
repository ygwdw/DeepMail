<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NSpin, NButton, NSpace, useMessage, NInput } from 'naive-ui'
import { emailsApi } from '@/api/emails'
import { chatApi } from '@/api/chat'
import { getErrorMessage } from '@/api/client'
import type { EmailRead } from '@/types/api'
import DraftEditor from '@/components/DraftEditor.vue'
import OriginalEmailCard from '@/components/OriginalEmailCard.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import ResizableSplit from '@/components/ResizableSplit.vue'

const router = useRouter()
const route = useRoute()
const message = useMessage()

const replyToEmail = ref<EmailRead | null>(null)
const draftContent = ref('')
const chatSessionId = ref<string | null>(null)
const loading = ref(false)
// v2-M12: 发件字段
const toInput = ref('')
const ccInput = ref('')
const subjectInput = ref('')
const sending = ref(false)

const initialPrompt = computed(() => {
  if (!replyToEmail.value) return ''
  const e = replyToEmail.value
  return `请帮我回复下面这封邮件（你已经是写信助手，先自我介绍并询问我希望的方向，再起草）：

主题：${e.subject}
发件人：${e.sender_name || ''} <${e.sender_email}>
收件人：${e.recipients.join(', ')}
时间：${e.sent_at}

正文：
${e.body_text}

起草时请用 <draft>...</draft> 标记包裹最终草稿正文。`
})

async function init(): Promise<void> {
  const replyTo = route.query.reply_to as string | undefined
  if (!replyTo) {
    // 无 reply_to，为空草稿
    return
  }
  loading.value = true
  try {
    replyToEmail.value = await emailsApi.detail(replyTo)
    // v2-M12: 预填收件人 + 主题（回复场景）
    if (replyToEmail.value) {
      toInput.value = replyToEmail.value.sender_email
      subjectInput.value = `Re: ${replyToEmail.value.subject || '(无主题)'}`
    }
    const session = await chatApi.createDraftReplySession(replyTo)
    chatSessionId.value = session.id
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

function onDraftFromChat(text: string): void {
  draftContent.value = text
  message.success('已填到左侧草稿编辑器')
}

async function onSend(): Promise<void> {
  const to = toInput.value.split(',').map((s) => s.trim()).filter(Boolean)
  if (to.length === 0) {
    message.warning('请填写收件人')
    return
  }
  if (!subjectInput.value.trim()) {
    message.warning('请填写主题')
    return
  }
  if (!draftContent.value.trim()) {
    message.warning('请填写正文')
    return
  }
  sending.value = true
  try {
    const cc = ccInput.value.split(',').map((s) => s.trim()).filter(Boolean)
    await emailsApi.send({
      to,
      cc,
      subject: subjectInput.value.trim(),
      body_text: draftContent.value,
    })
    message.success('已发送')
    router.push({ name: 'inbox' })
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    sending.value = false
  }
}

onMounted(init)
</script>

<template>
  <NSpin :show="loading">
    <div class="compose-page">
      <div class="page-header">
        <NButton text @click="router.back()">← 返回</NButton>
        <span class="page-title">
          {{ replyToEmail ? `回复：${replyToEmail.subject || '(无主题)'}` : '新建邮件' }}
        </span>
        <NSpace>
          <NButton type="primary" @click="onSend" :disabled="sending || !draftContent.trim()" :loading="sending">
            {{ sending ? '发送中' : '📤 发送' }}
          </NButton>
        </NSpace>
      </div>

      <ResizableSplit :initial-left-percent="60" :min-left-percent="35" :max-left-percent="75">
        <template #left>
          <div class="left-pane">
            <div class="compose-meta">
              <div class="meta-row">
                <span class="meta-label">收件人</span>
                <NInput v-model:value="toInput" placeholder="收件人邮箱（逗号分隔）" size="small" />
              </div>
              <div class="meta-row">
                <span class="meta-label">抄送</span>
                <NInput v-model:value="ccInput" placeholder="抄送（可选，逗号分隔）" size="small" />
              </div>
              <div class="meta-row">
                <span class="meta-label">主题</span>
                <NInput v-model:value="subjectInput" placeholder="邮件主题" size="small" />
              </div>
            </div>
            <DraftEditor v-model="draftContent" />
            <OriginalEmailCard v-if="replyToEmail" :email="replyToEmail" />
          </div>
        </template>
        <template #right>
          <ChatPanel
            v-if="chatSessionId"
            :session-id="chatSessionId"
            :initial-prompt="initialPrompt"
            @draft="onDraftFromChat"
          />
          <div v-else class="empty-ai">
            <span class="muted">📌 无关联邮件，无 AI 助手</span>
          </div>
        </template>
      </ResizableSplit>
    </div>
  </NSpin>
</template>

<style scoped>
.compose-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  margin: -16px;
  min-height: 0;
}
.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--n-divider-color);
  background: var(--n-card-color);
  flex-shrink: 0;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.compose-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
  padding: 10px;
  background: var(--n-card-color);
  border: 1px solid var(--n-divider-color);
  border-radius: 8px;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.meta-label {
  font-size: 12px;
  color: var(--n-text-color-3);
  width: 42px;
  flex-shrink: 0;
}
.left-pane {
  display: flex;
  flex-direction: column;
  padding: 16px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.left-pane > :first-child {
  flex: 1;
  min-height: 0;
}
.empty-ai {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  font-size: 13px;
}
</style>