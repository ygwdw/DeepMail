<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NInput, NSelect, NButton, NSpace, useMessage } from 'naive-ui'
import { chatApi } from '@/api/chat'
import { getErrorMessage } from '@/api/client'

const router = useRouter()
const message = useMessage()

const instruction = ref('给我写一封友好的自我介绍')
const creating = ref(false)

async function startChat(): Promise<void> {
  if (!instruction.value.trim()) {
    message.warning('请输入内容')
    return
  }
  creating.value = true
  try {
    const session = await chatApi.createSession(instruction.value.slice(0, 30))
    router.push({ name: 'chat', params: { sessionId: session.id }, query: { first: instruction.value } })
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <NCard title="发起新对话">
    <NSpace vertical>
      <div class="muted">在下方输入您的第一个问题，AI Agent 会自动调度邮件 / 待办 / 草稿 / 检索 / 整理等子任务。</div>
      <NInput
        v-model:value="instruction"
        type="textarea"
        :rows="4"
        placeholder="例如：今天有什么重要邮件？"
      />
      <NSpace>
        <NButton type="primary" :loading="creating" @click="startChat">开始对话</NButton>
        <NButton @click="router.push('/chat')">查看历史会话</NButton>
      </NSpace>
    </NSpace>
  </NCard>
</template>