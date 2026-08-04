<script setup lang="ts">
defineProps<{ description?: string }>()
</script>

<template>
  <div class="empty">
    <n-empty :description="description || '暂无数据'">
      <template #extra>
        <slot />
      </template>
    </n-empty>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40px;
  width: 100%;
}
</style>