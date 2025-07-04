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
      console.log('[ChatStore] Adding message:', message.sender, message.message.substring(0, 50));
      this.messages.push(message);
      console.log('[ChatStore] Total messages:', this.messages.length);
    },

    addUserMessage(text: string, userRole: '保健師' | '患者') {
      const icon = userRole === '保健師' ? 'mdi-account-tie-woman' : 'mdi-account';
      this.addMessage({
        sender: 'user',
        message: text,
        icon,
      });
    },

    addAssistantMessage(text: string, userRole: '保健師' | '患者') {
      const icon = userRole === '保健師' ? 'mdi-account' : 'mdi-account-tie-woman';
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