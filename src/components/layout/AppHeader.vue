<template>
  <v-card class="mb-4 pb-2 flex-shrink-0" rounded="xl" elevation="3">
    <v-card-title class="d-flex align-center text-h6 text-md-h5 font-weight-bold text-blue-darken-4" style="word-break: keep-all; white-space: wrap;">
      <v-icon start color="blue-darken-4">{{ icon }}</v-icon>
      <div>
        <div style="display: inline-block;">{{ title }}</div>
        <div v-if="subtitle" style="display: inline-block;">{{ subtitle }}</div>
      </div>
      <v-spacer></v-spacer>
      <v-btn 
        v-if="showMenuButton" 
        icon="mdi-menu" 
        color="blue-darken-4" 
        @click="$emit('toggle-drawer')"
      ></v-btn>
    </v-card-title>
    <v-card-subtitle v-if="showStatus || customStatus">
      <v-chip v-if="statusMessage" small :color="statusColor">{{ statusMessage }}</v-chip>
    </v-card-subtitle>
  </v-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useSessionStore } from '@/stores/sessionStore';
import { useChatStore } from '@/stores/chatStore';

interface Props {
  title?: string;
  subtitle?: string;
  icon?: string;
  showMenuButton?: boolean;
  showStatus?: boolean;
  customStatus?: string;
}

const props = withDefaults(defineProps<Props>(), {
  title: 'COVID-19患者積極的',
  subtitle: '疫学調査シミュレータ',
  icon: 'mdi-file-document-outline',
  showMenuButton: true,
  showStatus: true,
});

defineEmits<{
  'toggle-drawer': [];
}>();

const sessionStore = useSessionStore();
const chatStore = useChatStore();

const statusMessage = computed(() => {
  if (props.customStatus) return props.customStatus;
  if (!props.showStatus) return '';
  if (!sessionStore.user) return 'ロールを選択してください。';
  
  if (sessionStore.user.status === 'Established') {
    return '対話が開始されました。';
  }
  
  if (sessionStore.user.status === 'Waiting') {
    return '相手を待っています...';
  }
  
  return '接続中...';
});

const statusColor = computed(() => {
  if (props.customStatus) return 'primary';
  if (!props.showStatus || !sessionStore.user) return 'grey';
  
  switch (sessionStore.user.status) {
    case 'Established':
      return 'success';
    case 'Waiting':
      return 'warning';
    default:
      return 'info';
  }
});
</script>

<style scoped>
/* Header styles inherited from App.vue */
</style>
