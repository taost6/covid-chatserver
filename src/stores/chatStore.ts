import { defineStore } from 'pinia';
import type { ChatMessage } from '@/types';

interface ChatState {
  messages: ChatMessage[];
  inputText: string;
  isInputDisabled: boolean;
  isInputLocked: boolean;
}

export const useChatStore = defineStore('chat', {
  state: (): ChatState => ({
    messages: [],
    inputText: '',
    isInputDisabled: true,
    isInputLocked: false,
  }),

  getters: {
    canSendMessage: (state): boolean => 
      !state.isInputDisabled && 
      !state.isInputLocked && 
      state.inputText.trim().length > 0,
    
    messageCount: (state): number => 
      state.messages.length,
  },

  actions: {
    addMessage(message: ChatMessage) {
      console.log('[ChatStore] Input message:', { 
        type: typeof message.message, 
        sender: message.sender, 
        message: message.message 
      });
      
      // メッセージが文字列でない場合の安全な処理
      let processedMessage: string;
      if (typeof message.message === 'string') {
        processedMessage = message.message;
      } else if (message.message && typeof message.message === 'object') {
        console.error('[ChatStore] Object message detected:', message.message);
        console.log('[ChatStore] Object keys:', Object.keys(message.message));
        console.log('[ChatStore] Object values:', Object.values(message.message));
        processedMessage = JSON.stringify(message.message);
      } else {
        processedMessage = String(message.message || '');
      }
      
      const safeMessage = { ...message, message: processedMessage };
      console.log('[ChatStore] Final message:', safeMessage.sender, safeMessage.message.substring(0, 50));
      this.messages.push(safeMessage);
      console.log('[ChatStore] Total messages:', this.messages.length);
    },

    addUserMessage(text: string, userRole: '保健師' | '患者' | '傍聴者') {
      const icon = userRole === '保健師' ? 'mdi-account-tie-woman' : 
                   userRole === '傍聴者' ? 'mdi-eye-outline' : 'mdi-account';
      this.addMessage({
        sender: 'user',
        message: text,
        icon,
      });
    },

    addAssistantMessage(text: string, userRole: '保健師' | '患者' | '傍聴者') {
      const icon = userRole === '保健師' ? 'mdi-account' : 
                   userRole === '傍聴者' ? 'mdi-robot-outline' : 'mdi-account-tie-woman';
      this.addMessage({
        sender: 'assistant',
        message: text,
        icon,
      });
    },

    addSystemMessage(text: string) {
      this.addMessage({
        sender: 'system',
        message: text,
        icon: 'mdi-alert-circle-outline',
      });
    },

    // 傍聴者専用：保健師AIの発言（右側表示）
    addNurseAIMessage(text: string) {
      // Function call関連のテキストを含む場合は表示しない
      if (text.toLowerCase().includes('end_conversation_and_start_debriefing')) {
        return;
      }
      
      this.addMessage({
        sender: 'user', // 右側に表示させるためuserに設定
        message: text,
        icon: 'mdi-account-tie-woman',
      });
    },

    // 傍聴者専用：患者AIの発言（左側表示）
    addPatientAIMessage(text: string) {
      // Function call関連のテキストを含む場合は表示しない
      if (text.toLowerCase().includes('end_conversation_and_start_debriefing')) {
        return;
      }
      
      this.addMessage({
        sender: 'assistant', // 左側に表示させるためassistantに設定
        message: text,
        icon: 'mdi-account',
      });
    },

    setInputText(text: string) {
      this.inputText = text;
    },

    clearInputText() {
      this.inputText = '';
    },

    setInputDisabled(disabled: boolean) {
      this.isInputDisabled = disabled;
    },

    setInputLocked(locked: boolean) {
      this.isInputLocked = locked;
    },

    restoreMessages(messages: ChatMessage[]) {
      this.messages = [...messages];
    },

    clearMessages() {
      this.messages = [];
    },

    reset() {
      this.messages = [];
      this.inputText = '';
      this.isInputDisabled = true;
      this.isInputLocked = false;
    },
  },
});