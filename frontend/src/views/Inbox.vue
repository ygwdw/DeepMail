<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NInput, NSpin, useMessage } from 'naive-ui'
import { emailsApi } from '@/api/emails'
import { getErrorMessage } from '@/api/client'
import type { EmailListItem } from '@/types/api'
import EmailCard from '@/components/EmailCard.vue'
import EmptyState from '@/components/EmptyState.vue'

const router = useRouter()
const message = useMessage()

const folder = ref<'all' | 'inbox' | 'spam' | 'sent' | 'trash'>('all')
const keyword = ref('')
const loading = ref(false)
const syncing = ref(false)
const emails = ref<EmailListItem[]>([])
const total = ref(0)

const folderOptions = [
  { label: '全部', value: 'all' },
  { label: '收件箱', value: 'inbox' },
  { label: '已发', value: 'sent' },
  { label: '垃圾', value: 'spam' },
  { label: '回收站', value: 'trash' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await emailsApi.list({ limit: 100, folder: folder.value })
    emails.value = page.items
    total.value = page.total
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

async function onSync(): Promise<void> {
  syncing.value = true
  try {
    const r = await emailsApi.sync()
    message.success(`同步完成，新增 ${r.added} 封`)
    await load()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    syncing.value = false
  }
}

function open(id: string): void {
  router.push({ name: 'email-detail', params: { id } })
}

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return emails.value
  return emails.value.filter(
    (e) =>
      e.subject.toLowerCase().includes(k) ||
      e.sender_email.toLowerCase().includes(k) ||
      (e.sender_name || '').toLowerCase().includes(k),
  )
})

onMounted(load)
</script>

<template>
  <NCard>
    <NSpace align="center" style="margin-bottom: 12px" :wrap="false">
      <NSelect
        v-model:value="folder"
        :options="folderOptions"
        style="width: 120px"
        @update:value="load"
      />
      <NInput v-model:value="keyword" placeholder="搜索主题/发件人" clearable style="flex: 1" />
      <NButton @click="load" :loading="loading">刷新</NButton>
      <NButton type="primary" @click="onSync" :loading="syncing">同步</NButton>
      <span class="muted">共 {{ total }} 封</span>
    </NSpace>

    <NSpin :show="loading">
      <EmptyState v-if="filtered.length === 0" description="收件箱是空的">
        <NButton @click="onSync">从邮箱同步</NButton>
      </EmptyState>
      <div v-else class="email-list">
        <EmailCard
          v-for="email in filtered"
          :key="email.id"
          :email="email"
          @click="open"
        />
      </div>
    </NSpin>
  </NCard>
</template>

<style scoped>
.email-list {
  border: 1px solid var(--n-divider-color);
  border-radius: 4px;
}
</style>