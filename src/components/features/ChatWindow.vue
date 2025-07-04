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
          <span v-else>
            保健師
          </span>
        </v-toolbar-title>
      </v-toolbar>
      
      <v-card-text id="chat-history-container" ref="chatContainer">
        <MessageList :messages="chatStore.messages" />
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
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
</style>
