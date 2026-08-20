<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import json from 'highlight.js/lib/languages/json'
import css from 'highlight.js/lib/languages/css'
import xml from 'highlight.js/lib/languages/xml'
import 'highlight.js/styles/github-dark.css'
import type { ChatMessage } from '@/types/api'

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('json', json)
hljs.registerLanguage('css', css)
hljs.registerLanguage('xml', xml)

const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight: (str: string, lang: string): string => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code class="language-${lang}">${
          hljs.highlight(str, { language: lang }).value
        }</code></pre>`
      } catch {
        // fall through
      }
    }
    return `<pre class="hljs"><code>${escapeHtml(str)}</code></pre>`
  },
})

const props = withDefaults(
  defineProps<{ message: ChatMessage; streaming?: boolean; bare?: boolean }>(),
  { streaming: false, bare: false },
)

const html = computed(() => md.render(props.message.content || ''))
const role = computed(() => props.message.role)
</script>

<template>
  <!-- 用户消息：气泡样式（右对齐、蓝色） -->
  <div v-if="!bare && role === 'user'" class="bubble-wrap role-user">
    <div class="bubble user">
      <div class="content markdown-body" v-html="html" />
    </div>
  </div>

  <!-- 助手消息 bubble 模式：保留供外部调用 -->
  <div v-else-if="!bare && role === 'assistant'" class="bubble-wrap role-assistant">
    <div class="bubble assistant">
      <div class="content markdown-body" v-html="html" />
      <div v-if="streaming" class="cursor">▍</div>
    </div>
  </div>

  <!-- bare 模式：仅渲染 markdown 内容，不包气泡 -->
  <div v-else class="bare-content">
    <div class="markdown-body" v-html="html" />
    <div v-if="streaming" class="cursor">▍</div>
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
  max-width: 85%;
  padding: 14px 18px;
  border-radius: 16px;
  line-height: 1.7;
  word-break: break-word;
  font-size: 14px;
}
.bubble.user {
  background: var(--n-primary-color);
  color: white;
  border-bottom-right-radius: 4px;
  font-weight: 500;
  box-shadow: 0 2px 8px rgba(0, 100, 200, 0.15);
}
.bubble.assistant {
  background: var(--n-card-color);
  border: 1px solid var(--n-divider-color);
  color: var(--n-text-color-1);
  border-bottom-left-radius: 4px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.bare-content {
  /* 不包气泡，直接渲染 markdown */
  line-height: 1.7;
  word-break: break-word;
  color: var(--n-text-color-1);
  font-size: 14px;
}

.markdown-body :deep(p) {
  margin: 0 0 8px 0;
}
.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 12px 0 8px 0;
  font-weight: 600;
}
.markdown-body :deep(h1) { font-size: 20px; }
.markdown-body :deep(h2) { font-size: 18px; }
.markdown-body :deep(h3) { font-size: 16px; }
.markdown-body :deep(h4) { font-size: 14px; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}
.markdown-body :deep(li) {
  margin: 4px 0;
}
.markdown-body :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: ui-monospace, monospace;
}
.bubble.user .markdown-body :deep(code) {
  background: rgba(255, 255, 255, 0.2);
}
.markdown-body :deep(pre) {
  background: #0d1117;
  color: #c9d1d9;
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 8px 0;
  font-size: 12px;
  line-height: 1.5;
}
.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
  font-size: inherit;
}
.markdown-body :deep(a) {
  color: var(--n-primary-color);
  text-decoration: underline;
}
.bubble.user .markdown-body :deep(a) {
  color: white;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid var(--n-divider-color);
  padding-left: 12px;
  color: var(--n-text-color-3);
  margin: 8px 0;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--n-divider-color);
  padding: 6px 10px;
}
.markdown-body :deep(th) {
  background: var(--n-hover-color);
}
.markdown-body :deep(strong) {
  font-weight: 700;
}
.markdown-body :deep(em) {
  font-style: italic;
}
.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid var(--n-divider-color);
  margin: 12px 0;
}
.cursor {
  display: inline-block;
  animation: blink 1s infinite;
  margin-left: 2px;
  color: var(--n-primary-color);
}
@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
</style>