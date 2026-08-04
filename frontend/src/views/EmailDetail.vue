<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import {
  NCard, NSpace, NButton, NSpin, NTag, NDivider, NInput, NRadioGroup, NRadio,
  useMessage, NCollapse, NCollapseItem,
} from 'naive-ui'
import { emailsApi } from '@/api/emails'
import { aiApi } from '@/api/ai'
import { getErrorMessage } from '@/api/client'
import type { EmailRead } from '@/types/api'

const props = defineProps<{ id: string }>()
const router = useRouter()
const message = useMessage()

const loading = ref(false)
const email = ref<EmailRead | null>(null)

const skillLoading = ref<string | null>(null)
const skillResults = ref<Record<string, unknown>>({})

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

async function runSkill(name: string): Promise<void> {
  if (!email.value) return
  skillLoading.value = name
  try {
    let result: unknown
    if (name === 'process') {
      result = await aiApi.process(email.value.id)
    } else if (name === 'summary') {
      result = await aiApi.summary(email.value.id)
    } else if (name === 'todos') {
      result = await aiApi.todos(email.value.id)
    } else if (name === 'classify') {
      result = await aiApi.classify(email.value.id)
    } else if (name === 'spam') {
      result = await aiApi.spam(email.value.id)
    }
    skillResults.value[name] = result
    message.success(`${name} 完成`)
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    skillLoading.value = null
  }
}

// Draft
const draftInstruction = ref('礼貌确认')
const draftTone = ref<'auto' | 'formal' | 'casual'>('auto')
async function generateDraft(): Promise<void> {
  if (!email.value) return
  skillLoading.value = 'draft'
  try {
    const r = await emailsApi.draft(email.value.id, {
      instruction: draftInstruction.value,
      tone: draftTone.value,
    })
    skillResults.value['draft'] = r
    message.success('草稿生成完成')
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    skillLoading.value = null
  }
}

const sentAt = computed(() =>
  email.value ? dayjs(email.value.sent_at).format('YYYY-MM-DD HH:mm') : '',
)

onMounted(load)
</script>

<template>
  <NSpin :show="loading">
    <NCard v-if="email">
      <template #header>
        <div class="header-row">
          <NButton text @click="router.back()">← 返回</NButton>
          <span class="subject">{{ email.subject }}</span>
        </div>
      </template>
      <template #header-extra>
        <NSpace>
          <NTag v-if="email.folder === 'spam'" type="error">垃圾</NTag>
          <NTag v-for="c in email.categories" :key="c">{{ c }}</NTag>
        </NSpace>
      </template>

      <div class="meta muted">
        <div><strong>发件人：</strong>{{ email.sender_name }} &lt;{{ email.sender_email }}&gt;</div>
        <div><strong>收件人：</strong>{{ email.recipients.join(', ') }}</div>
        <div v-if="email.cc.length"><strong>抄送：</strong>{{ email.cc.join(', ') }}</div>
        <div><strong>时间：</strong>{{ sentAt }}</div>
        <div v-if="email.labels.length"><strong>标签：</strong>
          <NTag v-for="l in email.labels" :key="l" type="info" size="small" :bordered="false">#{{ l }}</NTag>
        </div>
      </div>

      <NDivider />

      <div v-if="email.summary" class="summary">
        <strong>AI 摘要：</strong>{{ email.summary }}
      </div>

      <pre class="body">{{ email.body_text }}</pre>

      <NDivider />

      <h3>AI 技能</h3>
      <NSpace>
        <NButton @click="runSkill('process')" :loading="skillLoading === 'process'">完整 process</NButton>
        <NButton @click="runSkill('summary')" :loading="skillLoading === 'summary'">摘要</NButton>
        <NButton @click="runSkill('todos')" :loading="skillLoading === 'todos'">提取待办</NButton>
        <NButton @click="runSkill('classify')" :loading="skillLoading === 'classify'">分类</NButton>
        <NButton @click="runSkill('spam')" :loading="skillLoading === 'spam'">垃圾评分</NButton>
      </NSpace>

      <NDivider />

      <h3>起草回复</h3>
      <NSpace align="center" :wrap="false">
        <NInput v-model:value="draftInstruction" placeholder="回复要求" style="flex: 1" />
        <NRadioGroup v-model:value="draftTone">
          <NRadio value="auto">auto</NRadio>
          <NRadio value="formal">正式</NRadio>
          <NRadio value="casual">轻松</NRadio>
        </NRadioGroup>
        <NButton type="primary" @click="generateDraft" :loading="skillLoading === 'draft'">生成草稿</NButton>
      </NSpace>

      <NCollapse v-if="Object.keys(skillResults).length" style="margin-top: 16px">
        <NCollapseItem v-for="(result, name) in skillResults" :key="name" :title="`${name} 结果`">
          <pre class="result">{{ JSON.stringify(result, null, 2) }}</pre>
        </NCollapseItem>
      </NCollapse>
    </NCard>
  </NSpin>
</template>

<style scoped>
.header-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.subject {
  font-weight: 600;
  font-size: 16px;
}
.meta {
  font-size: 13px;
  line-height: 1.8;
}
.summary {
  background: var(--n-hover-color);
  padding: 12px;
  border-radius: 4px;
  margin-bottom: 12px;
}
.body {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  line-height: 1.7;
}
.result {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  max-height: 400px;
  overflow: auto;
  background: var(--n-card-color);
  padding: 8px;
  border-radius: 4px;
}
</style>