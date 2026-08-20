<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NTabs, NTabPane, NCard, NSpace, NButton, NSpin, NTag, NInputNumber, useMessage, NTimeline, NTimelineItem, NEmpty, NDivider } from 'naive-ui'
import dayjs from 'dayjs'
import { memoryApi } from '@/api/memory'
import { getErrorMessage } from '@/api/client'
import type { EventDetailRead, EventRead, LongTermRead, TopicRead } from '@/types/api'

const message = useMessage()

const topics = ref<TopicRead[]>([])
const events = ref<EventRead[]>([])
const longTerm = ref<LongTermRead[]>([])
const loading = ref({ topics: false, events: false, long: false })

async function loadTopics(): Promise<void> {
  loading.value.topics = true
  try {
    topics.value = await memoryApi.listTopics(30, 100)
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.topics = false
  }
}

async function loadEvents(): Promise<void> {
  loading.value.events = true
  try {
    events.value = await memoryApi.listEvents(undefined, 100)
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.events = false
  }
}

async function loadLongTerm(): Promise<void> {
  loading.value.long = true
  try {
    longTerm.value = await memoryApi.listLongTerm(undefined, 0.1, 100)
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value.long = false
  }
}

// v2-P1: 手动触发 L2→L3 聚类（真聚类，幂等）
const clustering = ref(false)
const lastClusterRunAt = ref<string | null>(null)

async function runCluster(): Promise<void> {
  clustering.value = true
  try {
    const r = await memoryApi.runCluster(7, 2, 0.85)
    message.success(`新增 ${r.events_created} 个事件`)
    await Promise.all([loadEvents(), loadLastClusterRun()])
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    clustering.value = false
  }
}

async function loadLastClusterRun(): Promise<void> {
  try {
    const r = await memoryApi.lastClusterRun()
    lastClusterRunAt.value = r.last_run_at
  } catch (e) {
    // 静默：上次聚类时间获取失败不打扰用户
  }
}

async function runDecay(): Promise<void> {
  try {
    const r = await memoryApi.runDecay()
    message.success(`已更新 ${r.updated} 条衰减分数`)
    await loadLongTerm()
  } catch (e) {
    message.error(getErrorMessage(e))
  }
}

const detail = ref<EventDetailRead | null>(null)
async function viewEvent(id: string): Promise<void> {
  detail.value = await memoryApi.getEvent(id)
}

onMounted(() => {
  loadTopics()
  loadEvents()
  loadLongTerm()
  loadLastClusterRun()
})
</script>

<template>
  <NTabs type="line" animated default-value="topics">
    <NTabPane name="topics" tab="L2 话题">
      <NCard>
        <NSpace vertical>
          <NSpace>
            <NButton @click="loadTopics" :loading="loading.topics">刷新</NButton>
          </NSpace>
          <NSpin :show="loading.topics">
            <NEmpty v-if="topics.length === 0" description="还没有 L2 话题" />
            <div v-else class="topic-list">
              <NCard v-for="t in topics" :key="t.id" size="small" :title="t.topic" hoverable>
                <div>{{ t.summary }}</div>
                <div class="muted" style="margin-top: 8px">{{ dayjs(t.created_at).format('YYYY-MM-DD HH:mm') }}</div>
              </NCard>
            </div>
          </NSpin>
        </NSpace>
      </NCard>
    </NTabPane>

    <NTabPane name="events" tab="L3 事件">
      <NCard>
        <NSpace vertical>
          <NSpace align="center">
            <NButton @click="loadEvents" :loading="loading.events">刷新</NButton>
            <NButton type="primary" @click="runCluster" :loading="clustering">立即聚类</NButton>
            <span class="muted">
              上次聚类：{{ lastClusterRunAt ? dayjs(lastClusterRunAt).format('YYYY-MM-DD HH:mm') : '尚未聚类' }}
            </span>
          </NSpace>
          <NSpin :show="loading.events">
            <NEmpty v-if="events.length === 0" description="还没有 L3 事件" />
            <div v-else>
              <NCard
                v-for="e in events"
                :key="e.id"
                size="small"
                :title="e.title"
                hoverable
                style="margin-bottom: 8px"
                @click="viewEvent(e.id)"
              >
                <NSpace align="center">
                  <NTag size="small" :type="e.status === 'active' ? 'success' : 'default'">{{ e.status }}</NTag>
                  <span class="muted">confidence: {{ e.confidence.toFixed(2) }}</span>
                  <span class="muted">{{ dayjs(e.created_at).format('YYYY-MM-DD') }}</span>
                </NSpace>
                <div style="margin-top: 8px">{{ e.summary }}</div>
              </NCard>
            </div>
          </NSpin>
        </NSpace>

        <NDivider v-if="detail" />
        <NCard v-if="detail" :title="`时间线 - ${detail.title}`">
          <NTimeline>
            <NTimelineItem
              v-for="t in detail.timeline"
              :key="t.id"
              :type="t.event_type === 'milestone' ? 'success' : 'default'"
              :title="t.event_type"
              :time="dayjs(t.occurred_at).format('YYYY-MM-DD HH:mm')"
            >
              {{ t.content }}
            </NTimelineItem>
          </NTimeline>
        </NCard>
      </NCard>
    </NTabPane>

    <NTabPane name="long-term" tab="L4 长期">
      <NCard>
        <NSpace vertical>
          <NSpace>
            <NButton @click="loadLongTerm" :loading="loading.long">刷新</NButton>
            <NButton type="primary" @click="runDecay">跑衰减</NButton>
          </NSpace>
          <NSpin :show="loading.long">
            <NEmpty v-if="longTerm.length === 0" description="还没有 L4 长期记忆" />
            <NCard v-for="m in longTerm" :key="m.id" size="small" hoverable style="margin-bottom: 8px">
              <NSpace align="center">
                <NTag size="small" type="info">{{ m.category }}</NTag>
                <strong>{{ m.key }}</strong>
                <NTag size="small">decay: {{ m.decay_score.toFixed(3) }}</NTag>
                <NTag size="small">imp: {{ m.importance.toFixed(2) }}</NTag>
                <span class="muted">{{ dayjs(m.updated_at).format('YYYY-MM-DD') }}</span>
              </NSpace>
              <pre class="value">{{ JSON.stringify(m.value, null, 2) }}</pre>
            </NCard>
          </NSpin>
        </NSpace>
      </NCard>
    </NTabPane>
  </NTabs>
</template>

<style scoped>
.topic-list {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}
.value {
  margin-top: 8px;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>