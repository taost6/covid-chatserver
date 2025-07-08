<template>
  <v-navigation-drawer v-model="localDrawer" location="right" temporary width="360">
    <v-toolbar title="操作メニュー">
      <v-spacer></v-spacer>
      <v-btn icon="mdi-close" @click="closeDrawer"></v-btn>
    </v-toolbar>
    <v-divider></v-divider>
    <v-list nav dense>
      <v-list-item 
        title="このページを印刷する" 
        prepend-icon="mdi-printer" 
        @click="printPage"
      ></v-list-item>
    </v-list>
  </v-navigation-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue';

interface Props {
  modelValue: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
}>();

const localDrawer = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
});

const closeDrawer = () => {
  localDrawer.value = false;
};

const printPage = () => {
  // サイドバーを閉じる
  closeDrawer();
  // 印刷プレビューを表示
  setTimeout(() => {
    window.print();
  }, 100);
};
</script>

<style scoped>
/* Debriefing drawer styles */
</style>