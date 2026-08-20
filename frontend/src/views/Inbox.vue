<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NSpin, NEmpty, NSelect, useMessage, NButton, NCheckbox, NSpace } from 'naive-ui'
import { emailsApi } from '@/api/emails'
import { categoriesApi } from '@/api/categories'
import { labelsApi } from '@/api/labels'
import { getErrorMessage } from '@/api/client'
import type { EmailListItem } from '@/types/api'
import AppSidebar from '@/components/AppSidebar.vue'
import EmailListItemView from '@/components/EmailListItem.vue'
import EmptyState from '@/components/EmptyState.vue'

const router = useRouter()
const route = useRoute()
const message = useMessage()

const emails = ref<EmailListItem[]>([])
const loading = ref(false)
const labels = ref<Array<{ name: string; color: string }>>([])
const selectedLabelNames = ref<string[]>([])  // 多选标签过滤
const sidebarSelected = ref<string>(
  (route.query.filter as string) || 'all',
)

// v2-M12: 批量重新分类/打标
const selectedEmailIds = ref<Set<string>>(new Set())
const reclassifying = ref(false)

function toggleSelect(id: string, checked: boolean): void {
  const s = new Set(selectedEmailIds.value)
  if (checked) s.add(id)
  else s.delete(id)
  selectedEmailIds.value = s
}

function toggleSelectAll(checked: boolean): void {
  const s = new Set(selectedEmailIds.value)
  if (checked) {
    for (const e of filtered.value) s.add(e.id)
  } else {
    for (const e of filtered.value) s.delete(e.id)
  }
  selectedEmailIds.value = s
}

const allFilteredSelected = computed(
  () => filtered.value.length > 0 && filtered.value.every((e) => selectedEmailIds.value.has(e.id)),
)

async function reclassifySelected(doTag = true): Promise<void> {
  const ids = Array.from(selectedEmailIds.value)
  if (ids.length === 0) {
    message.warning('请先勾选要重新分类的邮件')
    return
  }
  reclassifying.value = true
  try {
    const r = await emailsApi.reclassify(ids, doTag)
    if (r.failed && r.failed.length > 0) {
      message.warning(`处理 ${r.processed} 封，失败 ${r.failed.length} 封`)
    } else {
      message.success(`已重新分类 ${r.processed} 封邮件`)
    }
    selectedEmailIds.value = new Set()
    await loadEmails()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    reclassifying.value = false
  }
}

const categories = ref<Awaited<ReturnType<typeof categoriesApi.list>>>([])

async function loadCategories(): Promise<void> {
  try {
    categories.value = await categoriesApi.list()
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

async function loadLabels(): Promise<void> {
  try {
    const ls = await labelsApi.list()
    labels.value = ls.map((l) => ({ name: l.name, color: l.color }))
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

async function loadEmails(): Promise<void> {
  loading.value = true
  try {
    const page = await emailsApi.list({ limit: 100, folder: 'all' })
    emails.value = page.items
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

function openEmail(id: string): void {
  router.push({ name: 'email-detail', params: { id } })
}

const filtered = computed(() => {
  let arr = emails.value

  // 侧栏过滤
  if (sidebarSelected.value === 'unread') {
    arr = arr.filter((e) => !e.is_read)
  } else {
    const sel = sidebarSelected.value
    if (sel !== 'all') {
      const cat = categories.value.find((c) => c.id === sel)
      if (cat) {
        if (cat.name === '常规') {
          arr = arr.filter((e) => e.categories.length === 0)
        } else {
          arr = arr.filter((e) => e.categories.includes(cat.name))
        }
      } else {
        const lb = labels.value.find((l) => l.name === sel)
        if (lb) arr = arr.filter((e) => (e.labels || []).includes(lb.name))
      }
    }
  }

  // 顶部多选标签过滤（与侧栏 AND 关系）
  if (selectedLabelNames.value.length > 0) {
    arr = arr.filter((e) => selectedLabelNames.value.every((n) => (e.labels || []).includes(n)))
  }
  return arr
})

function defaultCategoryFor(email: EmailListItem): string {
  if (email.categories && email.categories.length > 0) {
    return email.categories[0]
  }
  return '常规'
}

const labelOptions = computed(() =>
  labels.value.map((l) => ({ label: l.name, value: l.name })),
)

// 侧栏过滤激活时，顶部标签过滤收起（避免冗余）
const showTopFilter = computed(() => sidebarSelected.value === 'all')

watch(sidebarSelected, (v) => {
  if (v !== 'all') selectedLabelNames.value = []
})

onMounted(async () => {
  await Promise.all([loadCategories(), loadLabels()])
  await loadEmails()
})
</script>

<template>
  <div class="inbox-layout">
    <AppSidebar v-model:selected="sidebarSelected" />

    <div class="content">
      <NSpin :show="loading">
        <EmptyState v-if="filtered.length === 0" description="这里空空如也">
          <NButton @click="loadEmails">刷新</NButton>
        </EmptyState>
        <div v-else class="email-list">
          <div class="toolbar">
            <NSpace align="center">
              <NCheckbox
                :checked="allFilteredSelected"
                @update:checked="toggleSelectAll"
              >
                全选
              </NCheckbox>
              <span v-if="selectedEmailIds.size > 0" class="sel-count">
                已选 {{ selectedEmailIds.size }} 封
              </span>
              <NButton
                v-if="selectedEmailIds.size > 0"
                size="small"
                type="primary"
                :loading="reclassifying"
                :disabled="reclassifying"
                @click="reclassifySelected(true)"
              >
                重新分类+打标
              </NButton>
              <NButton
                v-if="selectedEmailIds.size > 0"
                size="small"
                :disabled="reclassifying"
                @click="reclassifySelected(false)"
              >
                仅重新分类
              </NButton>
              <NButton
                v-if="selectedEmailIds.size > 0"
                size="small"
                quaternary
                @click="selectedEmailIds = new Set()"
              >
                取消
              </NButton>
            </NSpace>
            <NSelect
              v-if="showTopFilter"
              v-model:value="selectedLabelNames"
              :options="labelOptions"
              multiple
              placeholder="按标签筛选..."
              clearable
              :max-tag-count="3"
              style="max-width: 400px"
            />
          </div>
          <EmailListItemView
            v-for="email in filtered"
            :key="email.id"
            :email="email"
            :category-name="defaultCategoryFor(email)"
            :labels="labels"
            :selectable="true"
            :selected="selectedEmailIds.has(email.id)"
            @click="openEmail"
            @toggle="toggleSelect"
          />
        </div>
      </NSpin>
    </div>
  </div>
</template>

<style scoped>
.inbox-layout {
  display: flex;
  height: 100%;
  gap: 0;
}
.content {
  flex: 1;
  padding: 12px 16px;
  overflow: auto;
}
.email-list {
  /* 填满宽度，不再 max-width 960px */
}
.toolbar {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--n-card-color);
  border-radius: 6px;
  border: 1px solid var(--n-divider-color);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sel-count {
  font-size: 12px;
  color: var(--n-primary-color);
}
.top-filter {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--n-card-color);
  border-radius: 6px;
  border: 1px solid var(--n-divider-color);
}
</style>