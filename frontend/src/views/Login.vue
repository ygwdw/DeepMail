<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NCard, NForm, NFormItem, NInput, NButton, NAlert, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const message = useMessage()

const username = ref('admin')
const password = ref('ChangeMe@2026')
const loading = ref(false)
const error = ref('')

async function onSubmit(): Promise<void> {
  error.value = ''
  loading.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    message.success('登录成功')
    const redirect = (route.query.redirect as string) || '/inbox'
    router.push(redirect)
  } catch (e) {
    error.value = getErrorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <NCard title="DeepMail 登录" class="login-card">
      <NAlert v-if="error" type="error" :title="error" closable @close="error = ''" style="margin-bottom: 12px" />
      <NForm @submit.prevent="onSubmit">
        <NFormItem label="用户名">
          <NInput v-model:value="username" placeholder="admin" autofocus />
        </NFormItem>
        <NFormItem label="密码">
          <NInput v-model:value="password" type="password" show-password-on="click" placeholder="ChangeMe@2026" />
        </NFormItem>
        <NButton type="primary" block :loading="loading" @click="onSubmit">登录</NButton>
      </NForm>
      <div class="hint muted">默认账户：admin / ChangeMe@2026</div>
    </NCard>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: var(--n-body-color);
}
.login-card {
  width: 360px;
}
.hint {
  margin-top: 12px;
  text-align: center;
}
</style>