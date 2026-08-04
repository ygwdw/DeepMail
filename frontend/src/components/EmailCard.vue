<script setup lang="ts">
import { computed } from 'vue'
import dayjs from 'dayjs'
import type { EmailListItem } from '@/types/api'

const props = defineProps<{ email: EmailListItem }>()
const emit = defineEmits<{ (e: 'click', id: string): void }>()

const time = computed(() => dayjs(props.email.received_at).format('YYYY-MM-DD HH:mm'))
const isUnread = computed(() => !props.email.is_read)

function onClick(): void {
  emit('click', props.email.id)
}
</script>

<template>
  <div class="email-card" :class="{ unread: isUnread }" @click="onClick">
    <div class="header">
      <div class="from truncate">
        <strong v-if="isUnread" class="dot">●</strong>
        {{ email.sender_name || email.sender_email }}
      </div>
      <div class="time muted">{{ time }}</div>
    </div>
    <div class="subject truncate">{{ email.subject }}</div>
    <div class="summary truncate muted">
      {{ email.summary || email.sender_email }}
    </div>
    <div class="tags">
      <n-tag v-if="email.folder === 'spam'" type="error" size="small">垃圾</n-tag>
      <n-tag v-for="c in email.categories" :key="c" size="small">{{ c }}</n-tag>
      <n-tag v-for="l in email.labels" :key="l" type="info" size="small" :bordered="false">#{{ l }}</n-tag>
    </div>
  </div>
</template>

<style scoped>
.email-card {
  padding: 12px 16px;
  border-bottom: 1px solid var(--n-divider-color);
  cursor: pointer;
  transition: background 0.15s;
}
.email-card:hover {
  background: var(--n-hover-color);
}
.email-card.unread .subject {
  font-weight: 600;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.from {
  font-size: 14px;
  max-width: 70%;
}
.dot {
  color: var(--n-primary-color);
  margin-right: 4px;
}
.subject {
  font-size: 14px;
  margin-bottom: 4px;
}
.summary {
  font-size: 12px;
}
.tags {
  margin-top: 6px;
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
</style>