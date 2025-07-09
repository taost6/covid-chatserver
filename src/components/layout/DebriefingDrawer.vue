<template>
  <v-navigation-drawer 
    v-model="localDrawer" 
    location="right" 
    temporary 
    width="360"
    :scrim="true"
    @click:outside="closeDrawer"
  >
    <v-toolbar title="操作メニュー">
      <v-spacer></v-spacer>
      <v-btn icon="mdi-close" @click="closeDrawer"></v-btn>
    </v-toolbar>
    <v-divider></v-divider>
    <v-list nav dense>
      <v-list-item title="文字の大きさ">
        <v-slider 
          v-model="fontSize" 
          @end="changeFontSize" 
          :ticks="{0:'小',1:'中',2:'大'}" 
          min="0" 
          max="2" 
          step="1" 
          show-ticks="always" 
          tick-size="2"
        ></v-slider>
      </v-list-item>
      
      <v-divider class="my-2"></v-divider>
      
      <v-list-item 
        title="このページを印刷する" 
        prepend-icon="mdi-printer" 
        @click="printPage"
      ></v-list-item>
    </v-list>
  </v-navigation-drawer>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';

interface Props {
  modelValue: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
}>();

const fontSize = ref(1);

const localDrawer = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
});

const closeDrawer = () => {
  localDrawer.value = false;
};

const changeFontSize = () => {
  localStorage.setItem('chatFontSize', fontSize.value.toString());
  // Trigger a re-render of components that use font size
  window.dispatchEvent(new Event('fontSizeChanged'));
};

const printPage = () => {
  // サイドバーを閉じる
  closeDrawer();
  // 印刷プレビューを表示
  setTimeout(() => {
    window.print();
  }, 100);
};

// Load font size from localStorage
onMounted(() => {
  const savedFontSize = localStorage.getItem('chatFontSize');
  if (savedFontSize) {
    fontSize.value = parseInt(savedFontSize, 10);
  }
});
</script>

<style scoped>
/* Debriefing drawer styles */
</style>