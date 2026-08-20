<script setup lang="ts">
import { ref, onMounted, h } from 'vue'
import {
  NCard, NSpace, NButton, NInput, NUpload, NSpin, NTag, NEmpty, useMessage,
  NDivider, NCollapse, NCollapseItem, NDataTable, NList, NListItem, NThing,
  NPopconfirm, NModal, NInputNumber, useDialog,
} from 'naive-ui'
import type { UploadFileInfo, DataTableColumns } from 'naive-ui'
import { knowledgeApi } from '@/api/knowledge'
import { getErrorMessage } from '@/api/client'
import type { KnowledgeHit, KnowledgePartition, KnowledgeStats } from '@/types/api'

const message = useMessage()
const dialog = useDialog()

const partition = ref('')
const uploadFile = ref<File | null>(null)
const stats = ref<KnowledgeStats | null>(null)
const searchQ = ref('')
const searchResults = ref<KnowledgeHit[]>([])
const loading = ref({ stats: false, search: false, upload: false, index: false })

// v2-M4.4: 分区 CRUD 弹窗状态
const renameDialog = ref({ show: false, oldName: '', newName: '' })
const deleteTarget = ref<KnowledgePartition | null>(null)

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
    if (r.kind === 'zip') {
      message.success(
        `已索引 zip 中 ${r.files_indexed?.length ?? 0} 个文件，共 ${r.chunks_indexed} 个 chunk`,
      )
    } else {
      message.success(`已索引 ${r.chunks_indexed} 个 chunk`)
    }
    uploadFile.value = null
    partition.value = ''
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

// v2-M4.4: 分区删除（带 inbox 系统分区保护 + 二次确认）
function confirmDeletePartition(p: KnowledgePartition): void {
  dialog.warning({
    title: '删除分区',
    content: `确认删除分区「${p.partition}」？该分区下 ${p.chunk_count} 个 chunk 将一并删除，且无法恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await knowledgeApi.deletePartition(p.partition)
        message.success(`已删除分区「${p.partition}」`)
        await loadStats()
      } catch (e) {
        message.error(getErrorMessage(e))
      }
    },
  })
}

// v2-M4.4: 分区重命名
function openRenameDialog(p: KnowledgePartition): void {
  renameDialog.value = { show: true, oldName: p.partition, newName: p.partition }
}

async function submitRename(): Promise<void> {
  const { oldName, newName } = renameDialog.value
  if (!newName.trim() || newName === oldName) {
    renameDialog.value.show = false
    return
  }
  try {
    const r = await knowledgeApi.renamePartition(oldName, newName.trim())
    message.success(`已将 ${r.renamed_chunks} 个 chunk 从「${oldName}」改名为「${newName}」`)
    renameDialog.value.show = false
    await loadStats()
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

// v2-M4.4: 分区列表 columns
const partitionColumns: DataTableColumns<KnowledgePartition> = [
  {
    title: '分区名',
    key: 'partition',
    render(row) {
      const isSystem = row.partition === 'inbox'
      return h('span', { class: 'partition-name' }, [
        row.partition,
        isSystem ? h(NTag, { type: 'info', size: 'small', style: 'margin-left: 8px' }, () => '系统') : null,
      ])
    },
  },
  { title: 'chunk 数', key: 'chunk_count' },
  {
    title: '操作',
    key: 'actions',
    width: 200,
    render(row) {
      if (row.partition === 'inbox') {
        return h('span', { class: 'hint-text' }, '系统分区不可修改')
      }
      return h(NSpace, {}, () => [
        h(
          NButton,
          { size: 'small', onClick: () => openRenameDialog(row) },
          () => '重命名',
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => confirmDeletePartition(row),
          },
          {
            default: () => `确认删除分区「${row.partition}」？`,
            trigger: () => h(NButton, { size: 'small', type: 'error' }, () => '删除'),
          },
        ),
      ])
    },
  },
]

onMounted(loadStats)
</script>

<template>
  <div class="kb-page">
    <NCard title="知识库分区" style="margin-bottom: 12px">
      <NSpace style="margin-bottom: 12px">
        <NButton @click="loadStats" :loading="loading.stats">刷新</NButton>
        <NButton type="primary" @click="indexEmails" :loading="loading.index">索引全部邮件</NButton>
      </NSpace>
      <NSpin :show="loading.stats">
        <NEmpty v-if="!stats || stats.partitions.length === 0" description="暂无分区；上传文档后会创建分区" />
        <NDataTable
          v-else
          :columns="partitionColumns"
          :data="stats.partitions"
          :pagination="false"
          size="small"
        />
      </NSpin>
    </NCard>

    <NCard title="上传文档" style="margin-bottom: 12px">
      <NSpace align="center" style="flex-wrap: wrap">
        <NInput v-model:value="partition" placeholder="分区名（如 contracts）" style="width: 200px" />
        <NUpload
          :default-upload="false"
          :max="1"
          accept=".txt,.md,.zip"
          @change="onFileChange"
        >
          <NButton>选择 .txt / .md / .zip</NButton>
        </NUpload>
        <NButton type="primary" :loading="loading.upload" @click="onUpload">上传</NButton>
      </NSpace>
      <div class="hint-text" style="margin-top: 8px">
        v2-M4.4: 支持 zip 上传（自动解压遍历 .txt/.md）；inbox 为系统分区不可删
      </div>
    </NCard>

    <NCard title="检索测试">
      <NSpace>
        <NInput
          v-model:value="searchQ"
          placeholder="输入 query"
          style="flex: 1"
          @keydown.enter="onSearch"
        />
        <NButton type="primary" @click="onSearch" :loading="loading.search">搜索</NButton>
      </NSpace>
      <NDivider />
      <NSpin :show="loading.search">
        <NEmpty v-if="searchResults.length === 0" description="暂无结果" />
        <NList v-else>
          <NListItem v-for="hit in searchResults" :key="hit.chunk_id">
            <NThing :title="`[${hit.partition} / ${hit.source ?? 'unknown'}] ${hit.filename ?? '(无文件名)'}`">
              <template #description>
                <NSpace>
                  <NTag size="small" type="success">score: {{ hit.score.toFixed(4) }}</NTag>
                  <NTag size="small" type="info">{{ hit.partition }}</NTag>
                  <NTag v-if="hit.filename" size="small">{{ hit.filename }}</NTag>
                  <!-- v2-M4.4: 溯源链接（邮件 → 跳 /emails/:id） -->
                  <NTag v-if="hit.metadata?.email_id" size="small" type="warning">
                    来源邮件
                  </NTag>
                </NSpace>
              </template>
              <div class="hit-content">{{ hit.content.slice(0, 400) }}{{ hit.content.length > 400 ? '...' : '' }}</div>
            </NThing>
          </NListItem>
        </NList>
      </NSpin>
    </NCard>

    <!-- v2-M4.4: 重命名分区弹窗 -->
    <NModal
      v-model:show="renameDialog.show"
      preset="dialog"
      title="重命名分区"
      positive-text="确认"
      negative-text="取消"
      @positive-click="submitRename"
    >
      <NSpace vertical>
        <div>原名：<strong>{{ renameDialog.oldName }}</strong></div>
        <NInput v-model:value="renameDialog.newName" placeholder="新分区名" />
      </NSpace>
    </NModal>
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
.partition-name {
  font-weight: 500;
}
.hint-text {
  font-size: 12px;
  color: #888;
}
</style>