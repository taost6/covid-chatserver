<template>
  <v-container>
    <v-card rounded="lg" elevation="2">
      <v-toolbar color="blue-darken-2" dark>
        <v-toolbar-title>
          <v-icon start>mdi-file-document-outline</v-icon>
          対話ログ詳細
        </v-toolbar-title>
        <v-spacer></v-spacer>
        <v-btn prepend-icon="mdi-arrow-left" @click="goBack">一覧へ戻る</v-btn>
        <v-btn prepend-icon="mdi-download" @click="downloadCSV">CSVダウンロード</v-btn>
      </v-toolbar>
      <v-card-subtitle class="pa-3">
        <strong>セッションID:</strong> {{ sessionId }}
      </v-card-subtitle>
      <v-divider></v-divider>
      <v-card-text class="pa-4">
        <div v-if="historyStore.isLoading" class="d-flex justify-center align-center fill-height">
          <v-progress-circular indeterminate color="primary" size="64"></v-progress-circular>
        </div>
        <div v-else>
          <MessageList 
            :messages="formattedMessages" 
            :show-timestamp="true"
          />
        </div>
      </v-card-text>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import { onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useHistoryStore } from '@/stores/historyStore';
import { CSVExporter } from '@/utils/csvExport';
import MessageList from '@/components/features/MessageList.vue';

const route = useRoute();
const router = useRouter();
const historyStore = useHistoryStore();

const sessionId = computed(() => route.params.sessionId as string);

onMounted(async () => {
  const id = sessionId.value;
  if (id) {
    try {
      await historyStore.fetchSessionDetail(id);
    } catch (error) {
      console.error('Failed to load session detail:', error);
    }
  } else {
    console.error('セッションIDが指定されていません。');
  }
});

const goBack = () => {
  router.push('/history');
};

const downloadCSV = async () => {
  const data = historyStore.currentSession.map(log => ({
    'ID': log.id,
    'Sender': log.sender,
    'Role': log.role,
    'Message': log.message.replace(/\n/g, ' '), // 改行をスペースに置換
    'Created At': new Date(log.created_at).toLocaleString()
  }));

  const csvContent = CSVExporter.generateCSV(
    ['ID', 'Sender', 'Role', 'Message', 'Created At'],
    data
  );

  const filename = `session_${sessionId.value}.csv`;
  await CSVExporter.downloadCSV(filename, csvContent);
};

// Format messages for MessageList component
const formattedMessages = computed(() => {
  return historyStore.currentSession.map(item => {
    let sender = item.sender.toLowerCase();
    
    // システムメッセージの場合はそのまま
    if (sender === 'system') {
      return {
        sender: 'system',
        message: item.message,
        icon: getIcon(item.sender, item.role),
        created_at: item.created_at
      };
    }
    
    // 傍聴者セッションの場合は、AIの発言を役割に応じて左右に配置
    if (item.role === '傍聴者') {
      // AIの発言の場合、ai_roleフィールドを使用して決定論的に判断
      if (sender === 'assistant' && item.ai_role) {
        // ai_roleフィールドを使用して発言者の役割を決定
        // 保健師AIの発言は右側（user）、患者AIの発言は左側（assistant）
        if (item.ai_role === '保健師') {
          sender = 'user'; // 保健師AIの発言は右側
        } else if (item.ai_role === '患者') {
          sender = 'assistant'; // 患者AIの発言は左側
        }
      }
    }
    
    return {
      sender: sender,
      message: item.message,
      icon: getIcon(item.sender, item.role),
      created_at: item.created_at
    };
  });
});

const getIcon = (sender: string, role: string) => {
  if (sender === 'User') {
    return role === '保健師' ? 'mdi-account-tie-woman' : 
           role === '傍聴者' ? 'mdi-eye-outline' : 'mdi-account';
  } else if (sender === 'Assistant') {
    return role === '患者' ? 'mdi-account' : 'mdi-account-tie-woman';
  } else if (sender === 'System') {
    // システムメッセージのアイコンを役割に応じて設定
    if (role === '評価者') {
      return 'mdi-file-chart';
    }
    return 'mdi-information-outline';
  }
  return 'mdi-robot';
};
</script>

<style scoped>
/* Styles are now handled by MessageList component */
</style>