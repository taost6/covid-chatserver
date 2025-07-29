<template>
  <div class="d-flex flex-column mt-4 chat-col" style="height: 100%;">
    <v-card id="chat-card" rounded="xl" elevation="3" style="flex: 1 1 auto; height: 100%;">
      <v-toolbar density="compact" color="grey-lighten-3">
        <v-toolbar-title class="text-subtitle-1 font-weight-bold">
          <v-icon 
            start 
            :color="sessionStore.isEstablished ? 'green' : 'orange'"
          >
            {{ sessionStore.isEstablished ? 'mdi-circle' : 'mdi-circle-outline' }}
          </v-icon>
          <span v-if="sessionStore.userRole === '保健師'">
            {{ patientStore.patientName || '患者' }}さん
            <span v-if="patientStore.patientInfo?.id">
              （患者ID: <span class="font-weight-bold text-blue-darken-3">{{ patientStore.patientInfo.id }}</span>）
            </span>
          </span>
          <span v-else-if="sessionStore.userRole === '傍聴者'">
            AI同士の対話を傍聴中
            <span v-if="patientStore.patientInfo?.id">
              （患者ID: <span class="font-weight-bold text-blue-darken-3">{{ patientStore.patientInfo.id }}</span>）
            </span>
          </span>
          <span v-else>
            保健師
          </span>
        </v-toolbar-title>
      </v-toolbar>
      
      <v-card-text id="chat-history-container" ref="chatContainer">
        <MessageList :messages="chatStore.messages" />
        
        <!-- Rate Limit Message -->
        <div v-if="chatStore.rateLimitMessage?.isVisible" class="mt-4">
          <v-alert
            type="warning"
            variant="tonal"
            class="ma-2"
            border="start"
            :title="`API制限による待機中 (残り${chatStore.rateLimitMessage.remainingSeconds}秒)`"
            :text="chatStore.rateLimitMessage.message"
            icon="mdi-clock-outline"
          >
            <template v-slot:append>
              <v-progress-circular
                :model-value="rateLimitProgress"
                size="32"
                width="4"
                color="warning"
              >
                {{ chatStore.rateLimitMessage.remainingSeconds }}
              </v-progress-circular>
            </template>
          </v-alert>
        </div>
      </v-card-text>
    </v-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import { useSessionStore } from '@/stores/sessionStore';
import { usePatientStore } from '@/stores/patientStore';
import { useChatStore } from '@/stores/chatStore';
import { useScrollToBottom } from '@/composables/useScrollToBottom';
import MessageList from '@/components/features/MessageList.vue';
import type { ChatMessage } from '@/types';

const sessionStore = useSessionStore();
const patientStore = usePatientStore();
const chatStore = useChatStore();
const { scrollToBottom: smoothScrollToBottom } = useScrollToBottom();

const chatContainer = ref<HTMLElement>();

// Rate limit progress calculation
const rateLimitProgress = computed(() => {
  if (!chatStore.rateLimitMessage) return 0;
  const { remainingSeconds, totalSeconds } = chatStore.rateLimitMessage;
  const elapsed = totalSeconds - remainingSeconds;
  return totalSeconds > 0 ? (elapsed / totalSeconds) * 100 : 0;
});

const scrollToBottom = async () => {
  console.log('[ChatWindow] scrollToBottom called');
  await smoothScrollToBottom();
};

watch(
  () => chatStore.messages.length,
  async (newLength, oldLength) => {
    console.log('[ChatWindow] Messages length changed:', oldLength, '->', newLength);

    if (newLength > (oldLength || 0)) {
      setTimeout(() => {
        console.log('[ChatWindow] Triggering scroll after DOM update');
        scrollToBottom();
      }, 100);
    }
  },
  { flush: 'post' }
);

defineExpose({
  scrollToBottom
});
</script>

<style>
.chat-col {
  height: 100%;
  max-height: calc(100%);
}

#chat-card {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
}

#chat-history-container {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}
</style>
