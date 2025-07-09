<template>
  <!-- 通常のチャット入力（保健師・患者用） -->
  <v-footer v-if="sessionStore.userRole !== '傍聴者'" app class="pa-4 footer-dark">
    <div class="d-flex align-end w-100">
      <v-textarea
        ref="textareaRef"
        v-model="chatStore.inputText"
        placeholder="150文字以内で入力してください（Shift+Enterで改行）"
        rows="2"
        auto-grow
        :max-rows="6"
        variant="outlined"
        density="comfortable"
        hide-details
        class="mr-3 message-textarea"
        :class="{
          'textarea-disabled': chatInputDisabled,
          'textarea-enabled': !chatInputDisabled
        }"
        :disabled="chatInputDisabled"
        @keydown.enter="handleEnterKey"
      ></v-textarea>
      <button 
        class="custom-send-button"
        :class="{
          'button-disabled': !chatStore.inputText.trim() || chatInputDisabled,
          'button-enabled': chatStore.inputText.trim() && !chatInputDisabled
        }"
        :disabled="!chatStore.inputText.trim() || chatInputDisabled"
        @click="submitChatInputText"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M2,21L23,12L2,3V10L17,12L2,14V21Z" />
        </svg>
      </button>
    </div>
  </v-footer>
  
  <!-- 傍聴者用の中断ボタン -->
  <v-footer v-if="sessionStore.userRole === '傍聴者'" app class="pa-4 footer-dark">
    <div class="d-flex justify-center w-100">
      <v-btn 
        color="warning" 
        variant="elevated" 
        size="large"
        @click="$emit('interrupt-session-with-debrief')"
        prepend-icon="mdi-stop-circle-outline"
        class="px-6"
      >
        対話を中断して評価を実行する
      </v-btn>
    </div>
  </v-footer>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { useChatStore } from '@/stores/chatStore';
import { useSessionStore } from '@/stores/sessionStore';
import { useWebSocket } from '@/composables/useWebSocket';
import { useFocus } from '@/composables/useFocus';
import { useScrollToBottom } from '@/composables/useScrollToBottom';

const emit = defineEmits<{
  'interrupt-session-with-debrief': [];
}>();

const chatStore = useChatStore();
const sessionStore = useSessionStore();
const { sendChatMessage } = useWebSocket();
const { setTextareaRef, focusTextarea } = useFocus();
const { scrollToBottom } = useScrollToBottom();

// Template ref for textarea
const textareaRef = ref();

// Compute disabled state exactly like original
const chatInputDisabled = computed(() => {
  return chatStore.isInputDisabled || chatStore.isInputLocked;
});

const handleEnterKey = (e: KeyboardEvent) => {
  // Get settings from localStorage exactly like original
  const confSubmitWithEnter = localStorage.getItem('confSubmitWithEnter') !== 'false';
  
  if (confSubmitWithEnter && !e.shiftKey) {
    e.preventDefault();
    submitChatInputText();
  } else if (e.ctrlKey) {
    e.preventDefault();
    submitChatInputText();
  }
};

const submitChatInputText = async () => {
  const text = chatStore.inputText.trim();
  if (!text || chatStore.isInputLocked || sessionStore.user?.status !== 'Established') return;

  try {
    sendChatMessage(text);
    
    // Clear input if setting is enabled, exactly like original
    const confSubmitThenClear = localStorage.getItem('confSubmitThenClear') !== 'false';
    if (confSubmitThenClear) {
      chatStore.clearInputText();
    }
    
    // フォーカスを維持し、スクロールする
    setTimeout(() => {
      focusTextarea();
      scrollToBottom();
    }, 100);
  } catch (error) {
    console.error('Failed to send message:', error);
  }
};

// Set textarea ref for global focus management
onMounted(() => {
  setTextareaRef(textareaRef.value);
});
</script>

<style scoped>
/* Footer dark theme */
.footer-dark {
  background-color: #1e293b !important;
}

/* Message textarea styling */
.message-textarea {
  background-color: #1e293b !important;
}

.message-textarea :deep(*),
.message-textarea :deep(*::before),
.message-textarea :deep(*::after) {
  -webkit-mask-image: none !important;
  mask-image: none !important;
}

.message-textarea :deep(.v-field) {
  background-color: #1e293b !important;
  color: #ffffff !important;
  border-radius: 16px !important;
  min-height: 56px !important;
  max-height: 140px !important;
  -webkit-mask-image: none !important;
  mask-image: none !important;
}

.message-textarea :deep(.v-field__field) {
  background-color: #1e293b !important;
  color: #ffffff !important;
  padding: 16px !important;
  display: flex !important;
  align-items: flex-start !important;
  line-height: 1.4 !important;
  -webkit-mask-image: none !important;
  mask-image: none !important;
  min-height: 24px !important;
}

.message-textarea :deep(.v-field__outline) {
  border-color: rgba(255, 255, 255, 0.2) !important;
}

.message-textarea :deep(.v-field__outline__start) {
  border-color: rgba(255, 255, 255, 0.2) !important;
}

.message-textarea :deep(.v-field__outline__end) {
  border-color: rgba(255, 255, 255, 0.2) !important;
}

.message-textarea:not(.textarea-disabled) :deep(.v-field--focused .v-field__outline) {
  border-color: #ffffff !important;
}

.message-textarea:not(.textarea-disabled) :deep(.v-field--focused .v-field__outline__start) {
  border-color: #ffffff !important;
}

.message-textarea:not(.textarea-disabled) :deep(.v-field--focused .v-field__outline__end) {
  border-color: #ffffff !important;
}

.message-textarea:not(.textarea-disabled) :deep(.v-field--active .v-field__outline) {
  border-color: rgba(255, 255, 255, 0.4) !important;
}

.message-textarea:not(.textarea-disabled) :deep(.v-field--active .v-field__outline__start) {
  border-color: rgba(255, 255, 255, 0.4) !important;
}

.message-textarea:not(.textarea-disabled) :deep(.v-field--active .v-field__outline__end) {
  border-color: rgba(255, 255, 255, 0.4) !important;
}

.message-textarea :deep(.v-field__input) {
  padding: 0 !important;
  align-items: flex-start !important;
  min-height: 24px !important;
  -webkit-mask-image: none !important;
  mask-image: none !important;
  overflow-y: auto !important;
}

.message-textarea :deep(.v-field__input textarea) {
  color: #ffffff !important;
  line-height: 1.4 !important;
  -webkit-mask-image: none !important;
  mask-image: none !important;
}

.message-textarea :deep(.v-field__input textarea::placeholder) {
  color: rgba(255, 255, 255, 0.6) !important;
}

/* Disabled state */
.message-textarea.textarea-disabled {
  background-color: rgba(30, 41, 59, 0.5) !important;
  opacity: 0.6;
}

.message-textarea.textarea-disabled :deep(.v-field__field) {
  background-color: rgba(30, 41, 59, 0.5) !important;
  color: rgba(255, 255, 255, 0.4) !important;
}

.message-textarea.textarea-disabled :deep(.v-field__outline) {
  border-color: rgba(255, 255, 255, 0.1) !important;
}

/* Custom send button */
.custom-send-button {
  width: 56px;
  min-height: 56px;
  height: auto;
  border-radius: 16px;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 0;
  outline: none;
  align-self: flex-end;
}

.custom-send-button.button-enabled {
  background-color: #1e293bb3;
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.custom-send-button.button-enabled:hover {
  background-color: #334155;
  border-color: rgba(255, 255, 255, 0.4);
  transform: translateY(-1px);
}

.custom-send-button.button-enabled:active {
  transform: translateY(0);
  background-color: #475569;
}

.custom-send-button.button-disabled {
  background-color: rgba(30, 41, 59, 0.3);
  color: rgba(255, 255, 255, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.1);
  cursor: not-allowed;
}

.custom-send-button svg {
  transition: transform 0.2s ease;
}

.custom-send-button.button-enabled:hover svg {
  transform: translateX(2px);
}
</style>