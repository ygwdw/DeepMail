<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NSpin, NSpace, NInputNumber, NButton, NDivider, NAlert, useMessage } from 'naive-ui'
import { meApi } from '@/api/me'
import { getErrorMessage } from '@/api/client'
import type { MeRead } from '@/types/api'

const message = useMessage()
const me = ref<MeRead | null>(null)
const tokenBudget = ref(8000)
const saving = ref(false)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    me.value = await meApi.get()
    tokenBudget.value = me.value.token_budget
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  saving.value = true
  try {
    me.value = await meApi.patchTokenBudget(tokenBudget.value)
    message.success('已保存')
  } catch (e) {
    message.error(getErrorMessage(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <NCard title="账户设置">
    <NSpin :show="loading">
      <NAlert v-if="me" type="info" :show-icon="false">
        用户名：<strong>{{ me.username }}</strong> ｜ 角色：<strong>{{ me.role }}</strong>
      </NAlert>
      <NDivider />
      <NSpace vertical>
        <div>
          <div class="label">Token 预算（决定多轮摘要触发阈值）</div>
          <NAlert type="warning" :show-icon="false" style="margin: 8px 0">
            建议范围 4000–32000。值越大，触发压缩的历史越长；越小越频繁触发。
          </NAlert>
          <NSpace>
            <NInputNumber
              v-model:value="tokenBudget"
              :min="2000"
              :max="32000"
              :step="1000"
              placeholder="8000"
            />
            <NButton type="primary" :loading="saving" @click="save">保存</NButton>
          </NSpace>
        </div>
      </NSpace>
    </NSpin>
  </NCard>
</template>

<style scoped>
.label {
  font-weight: 600;
  margin-bottom: 4px;
}
</style>