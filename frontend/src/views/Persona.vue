<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NCard, NSpace, NButton, NSpin, NDescriptions, NDescriptionsItem, NTag,
  useMessage, NAlert, NEmpty, NDivider,
} from 'naive-ui'
import dayjs from 'dayjs'
import { personaApi } from '@/api/persona'
import { getErrorMessage } from '@/api/client'
import type { PersonaRead } from '@/types/api'

const message = useMessage()
const loading = ref(false)
const persona = ref<PersonaRead | null>(null)

const fieldLabels: Record<string, string> = {
  name: '姓名',
  age: '年龄',
  education: '教育背景',
  profession: '职业',
  personality: '性格',
  communication_style: '沟通风格',
  language_pref: '语言偏好',
  signature: '签名',
  frequent_topics: '常聊话题',
  sample_phrases: '常用短语',
}

async function load(): Promise<void> {
  loading.value = true
  try {
    persona.value = await personaApi.get()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

async function clearAll(): Promise<void> {
  try {
    await personaApi.clear()
    message.success('已清空')
    await load()
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

async function rollback(): Promise<void> {
  try {
    persona.value = await personaApi.rollback()
    message.success('已回滚')
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

function renderValue(v: unknown): string {
  if (Array.isArray(v)) return v.join('、')
  if (v === null || v === undefined || v === '') return '（未填）'
  return String(v)
}

onMounted(load)
</script>

<template>
  <NCard title="人格画像">
    <NSpace vertical>
      <NAlert type="info" :show-icon="false">
        DeepMail 通过 LLM 自主决策（OpenClaw 模式）在每轮对话后自动更新画像；用户也可手动 PATCH 或回滚。
      </NAlert>
      <NSpace>
        <NButton @click="load" :loading="loading">刷新</NButton>
        <NButton type="error" ghost @click="clearAll">清空</NButton>
        <NButton type="warning" ghost @click="rollback">回滚</NButton>
      </NSpace>
      <NSpin :show="loading">
        <NEmpty
          v-if="!persona || Object.keys(persona.profile_json).length === 0"
          description="还没有画像；继续对话让 LLM 自动学习"
        />
        <NCard v-else>
          <NDescriptions :column="2" bordered>
            <NDescriptionsItem v-for="(v, k) in persona.profile_json" :key="k" :label="fieldLabels[k] || k">
              <span v-if="Array.isArray(v)">
                <NTag v-for="item in v" :key="item" style="margin-right: 4px">{{ item }}</NTag>
              </span>
              <span v-else>{{ renderValue(v) }}</span>
            </NDescriptionsItem>
          </NDescriptions>
          <NDivider />
          <div class="muted">最后更新：{{ dayjs(persona.updated_at).format('YYYY-MM-DD HH:mm:ss') }}</div>
        </NCard>
      </NSpin>
    </NSpace>
  </NCard>
</template>