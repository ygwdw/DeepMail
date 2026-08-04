<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  NCard, NSpace, NButton, NInput, NUpload, NSpin, NTag, NEmpty, useMessage,
  NDivider, NCollapse, NCollapseItem, NDataTable, NList, NListItem, NThing,
} from 'naive-ui'
import type { UploadFileInfo } from 'naive-ui'
import { knowledgeApi } from '@/api/knowledge'
import { getErrorMessage } from '@/api/client'
import type { KnowledgeHit, KnowledgeStats } from '@/types/api'

const message = useMessage()

const partition = ref('')
const uploadFile = ref<File | null>(null)
const stats = ref<KnowledgeStats | null>(null)
const searchQ = ref('')
const searchResults = ref<KnowledgeHit[]>([])
const loading = ref({ stats: false, search: false, upload: false, index: false })

async function loadStats(): Promise<void> {
  loading.value.stats = true
  try {
    stats.value = await knowledgeApi.stats()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.stats = false
  }
}

async function onUpload(): Promise<void> {
  if (!partition.value.trim() || !uploadFile.value) {
    message.warning('请填写分区名并选择文件')
    return
  }
  loading.value.upload = true
  try {
    const r = await knowledgeApi.upload(partition.value.trim(), uploadFile.value)
    message.success(`已索引 ${r.chunks_indexed} 个 chunk`)
    uploadFile.value = null
    await loadStats()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.upload = false
  }
}

async function indexEmails(): Promise<void> {
  loading.value.index = true
  try {
    const r = await knowledgeApi.indexEmails(1000)
    message.success(`已索引 ${r.chunks_indexed} 封邮件`)
    await loadStats()
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.index = false
  }
}

async function onSearch(): Promise<void> {
  if (!searchQ.value.trim()) return
  loading.value.search = true
  try {
    const r = await knowledgeApi.search({ query: searchQ.value, top_k: 10, use_rerank: true })
    searchResults.value = r.hits
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.search = false
  }
}

function onFileChange({ fileList }: { fileList: UploadFileInfo[] }): void {
  if (fileList.length > 0 && fileList[0].file) {
    uploadFile.value = fileList[0].file
  } else {
    uploadFile.value = null
  }
}

onMounted(loadStats)
</script>

<template>
  <div class="kb-page">
    <NCard title="知识库状态" style="margin-bottom: 12px">
      <NSpace v-if="stats">
        <NTag type="info">总 chunk: {{ stats.total_chunks }}</NTag>
        <NTag v-for="p in stats.partitions" :key="p.partition" type="success">
          {{ p.partition }}: {{ p.count }}
        </NTag>
      </NSpace>
      <NEmpty v-else description="加载中..." />
      <NDivider />
      <NSpace>
        <NButton @click="loadStats" :loading="loading.stats">刷新</NButton>
        <NButton type="primary" @click="indexEmails" :loading="loading.index">索引全部邮件</NButton>
      </NSpace>
    </NCard>

    <NCard title="上传文档" style="margin-bottom: 12px">
      <NSpace align="center">
        <NInput v-model:value="partition" placeholder="分区名（如 contracts）" style="width: 200px" />
        <NUpload :default-upload="false" :max="1" accept=".txt,.md" @change="onFileChange">
          <NButton>选择 .txt / .md</NButton>
        </NUpload>
        <NButton type="primary" :loading="loading.upload" @click="onUpload">上传</NButton>
      </NSpace>
    </NCard>

    <NCard title="检索测试">
      <NSpace>
        <NInput v-model:value="searchQ" placeholder="输入 query" style="flex: 1" @keydown.enter="onSearch" />
        <NButton type="primary" @click="onSearch" :loading="loading.search">搜索</NButton>
      </NSpace>
      <NDivider />
      <NSpin :show="loading.search">
        <NEmpty v-if="searchResults.length === 0" description="暂无结果" />
        <NList v-else>
          <NListItem v-for="hit in searchResults" :key="hit.chunk_id">
            <NThing :title="`[${hit.partition}] ${hit.filename || hit.source || hit.chunk_id}`">
              <template #description>
                <NSpace>
                  <NTag size="small" type="success">score: {{ hit.score.toFixed(4) }}</NTag>
                  <NTag size="small">{{ hit.source }}</NTag>
                </NSpace>
              </template>
              <div class="hit-content">{{ hit.content.slice(0, 400) }}{{ hit.content.length > 400 ? '...' : '' }}</div>
            </NThing>
          </NListItem>
        </NList>
      </NSpin>
    </NCard>
  </div>
</template>

<style scoped>
.kb-page {
  width: 100%;
}
.hit-content {
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>