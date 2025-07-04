<template>
  <div>
    <div 
      v-for="(message, index) in messages" 
      :key="index" 
      class="d-flex mb-3" 
      :class="getJustify(message.sender)"
    >
      <v-sheet 
        max-width="75%" 
        class="pa-3 elevation-1" 
        :class="getBubbleClass(message.sender, message.message)"
      >
        <div class="d-flex align-start">
          <v-icon 
            class="mr-2 mt-1 flex-shrink-0" 
            size="small"
            :color="getIconColor(message.sender, message.message)"
          >
            {{ message.icon }}
          </v-icon>
          <div :class="fontSizeClass" class="message-text" v-html="processMessage(message.message)"></div>
        </div>
        <div 
          v-if="showTimestamp"
          class="text-caption text-right mt-2" 
          :class="getTimestampColor(message.sender)"
          style="margin-left: 28px;"
        >
          {{ formatTimestamp(message.timestamp || message.created_at) }}
        </div>
      </v-sheet>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';

interface Message {
  sender: string;
  message: string;
  icon: string;
  timestamp?: string;
  created_at?: string;
}

interface Props {
  messages: Message[];
  showTimestamp?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  showTimestamp: false
});

const router = useRouter();

const fontSizeClass = computed(() => {
  const fontSize = parseInt(localStorage.getItem('chatFontSize') || '1');
  switch (fontSize) {
    case 0: return 'text-caption';
    case 1: return 'text-body-1';
    case 2: return 'text-h6';
    default: return 'text-body-1';
  }
});

const getJustify = (sender: string) => {
  if (sender === 'user' || sender === 'User') return 'justify-end';
  if (sender === 'assistant' || sender === 'Assistant') return 'justify-start';
  return 'justify-center';
};

const getBubbleClass = (sender: string, message?: string) => {
  if (sender === 'user' || sender === 'User') return 'message-bubble-user';
  if (sender === 'assistant' || sender === 'Assistant') return 'message-bubble-assistant';
  
  // System messages: check if it's an error or info message
  if (sender === 'system' || sender === 'System') {
    if (message && isErrorMessage(message)) {
      return 'message-bubble-system-error';
    }
    return 'message-bubble-system-info';
  }
  
  return 'message-bubble-system-info';
};

const getIconColor = (sender: string, message?: string) => {
  if (sender === 'user' || sender === 'User') return 'white';
  if (sender === 'assistant' || sender === 'Assistant') return 'blue-darken-2';
  
  // System messages: check if it's an error or info message
  if (sender === 'system' || sender === 'System') {
    if (message && isErrorMessage(message)) {
      return 'red-darken-2';
    }
    return 'green-darken-2';
  }
  
  return 'green-darken-2';
};

const isErrorMessage = (message: string) => {
  const errorKeywords = [
    'エラー', 'error', 'Error', 'ERROR',
    '失敗', 'failed', 'Failed', 'FAILED',
    '問題', 'problem', 'Problem',
    '接続できません', 'connection', 'timeout',
    'システムエラー'
  ];
  
  return errorKeywords.some(keyword => 
    message.toLowerCase().includes(keyword.toLowerCase())
  );
};

const getTimestampColor = (sender: string) => {
  if (sender === 'user' || sender === 'User') return 'text-blue-lighten-4';
  return 'text-grey-darken-1';
};

const formatTimestamp = (timestamp: string) => {
  if (!timestamp) return '';
  return new Date(timestamp).toLocaleString();
};

// Process message to handle markdown links and sanitize HTML
const processMessage = (message: string) => {
  // Escape HTML first
  const escaped = message
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
  
  // Convert markdown-style links [text](url) to HTML links
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  const processed = escaped.replace(linkRegex, (match, text, url) => {
    // Handle internal routes
    if (url.startsWith('/')) {
      return `<a href="#" onclick="handleInternalLink('${url}'); return false;" class="system-link">${text}</a>`;
    }
    // Handle external links
    return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="system-link">${text}</a>`;
  });
  
  return processed;
};

// Setup global link handler on mount
onMounted(() => {
  (window as any).handleInternalLink = (url: string) => {
    router.push(url);
  };
});
</script>

<style scoped>
.message-bubble-user {
  background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%) !important;
  color: white !important;
  box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2) !important;
  border-radius: 16px 16px 4px 16px !important;
}

.message-bubble-assistant {
  background-color: #f8fafc !important;
  color: #334155 !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1) !important;
  border-radius: 16px 16px 16px 4px !important;
}

.message-bubble-system-error {
  background-color: #fef2f2 !important;
  color: #dc2626 !important;
  border: 1px solid #fecaca !important;
  box-shadow: 0 1px 3px rgba(220, 38, 38, 0.1) !important;
  border-radius: 12px !important;
}

.message-bubble-system-info {
  background-color: #f0fdf4 !important;
  color: #166534 !important;
  border: 1px solid #bbf7d0 !important;
  box-shadow: 0 1px 3px rgba(34, 197, 94, 0.1) !important;
  border-radius: 12px !important;
}

.message-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
}

.message-text :deep(.system-link) {
  color: #1976d2;
  text-decoration: underline;
  cursor: pointer;
  font-weight: 500;
}

.message-text :deep(.system-link:hover) {
  color: #1565c0;
  text-decoration: none;
}
</style>