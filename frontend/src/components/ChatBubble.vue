<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '@/types/api'

const props = defineProps<{ message: ChatMessage; streaming?: boolean }>()

const role = computed(() => props.message.role)
</script>

<template>
  <div class="bubble-wrap" :class="`role-${role}`">
    <div class="bubble">
      <div class="content">{{ message.content }}</div>
      <div v-if="streaming" class="streaming">▍</div>
    </div>
  </div>
</template>

<style scoped>
.bubble-wrap {
  display: flex;
  margin: 8px 0;
}
.bubble-wrap.role-user {
  justify-content: flex-end;
}
.bubble-wrap.role-assistant {
  justify-content: flex-start;
}
.bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}
.role-user .bubble {
  background: var(--n-primary-color);
  color: white;
}
.role-assistant .bubble {
  background: var(--n-card-color);
  border: 1px solid var(--n-divider-color);
}
.streaming {
  display: inline-block;
  animation: blink 1s infinite;
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>