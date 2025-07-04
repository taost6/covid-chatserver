import { ref, nextTick } from 'vue';

// グローバルなフォーカス管理
const textareaRef = ref<any>(null);

export function useFocus() {
  const setTextareaRef = (ref: any) => {
    textareaRef.value = ref;
  };

  const focusTextarea = async () => {
    await nextTick();
    if (textareaRef.value && textareaRef.value.$el) {
      const textarea = textareaRef.value.$el.querySelector('textarea');
      if (textarea) {
        textarea.focus();
      }
    }
  };

  return {
    setTextareaRef,
    focusTextarea,
  };
}