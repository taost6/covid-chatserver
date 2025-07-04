<template>
  <v-container>
    <v-card rounded="lg" elevation="2">
      <v-toolbar color="blue-darken-2" dark>
        <v-toolbar-title>
          <v-icon start>mdi-history</v-icon>
          対話ログ一覧
        </v-toolbar-title>
        <v-spacer></v-spacer>
        <v-btn prepend-icon="mdi-download" @click="downloadCSV">CSVダウンロード</v-btn>
      </v-toolbar>
      <v-card-text>
        <v-data-table
          v-model:page="page"
          v-model:items-per-page="itemsPerPage"
          :headers="headers"
          :items="historyStore.formattedSessions"
          :loading="historyStore.isLoading"
          class="elevation-1"
          hover
          @click:row="showDetail"
        >
        </v-data-table>
      </v-card-text>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useHistoryStore } from '@/stores/historyStore';
import { CSVExporter } from '@/utils/csvExport';

const router = useRouter();
const historyStore = useHistoryStore();

const headers = [
  { title: '役割', key: 'user_role', sortable: true },
  { title: '名前', key: 'user_name', sortable: true },
  { title: '患者ID', key: 'patient_id', sortable: true },
  { title: '開始日時', key: 'started_at', sortable: true },
  { title: 'セッションID', key: 'session_id', sortable: false },
];

const page = computed({
  get: () => historyStore.tableState.page,
  set: (value) => historyStore.setTablePage(value)
});

const itemsPerPage = computed({
  get: () => historyStore.tableState.itemsPerPage,
  set: (value) => historyStore.setTableItemsPerPage(value)
});

onMounted(async () => {
  historyStore.loadTableState();
  try {
    await historyStore.fetchSessions();
    // Apply saved page after data is loaded
    historyStore.loadTableState();
  } catch (error) {
    console.error('Failed to load session history:', error);
  }
});

const showDetail = (event: Event, { item }: { item: any }) => {
  router.push(`/history/${item.session_id}`);
};

const downloadCSV = async () => {
  const data = historyStore.formattedSessions.map(session => ({
    '役割': session.user_role,
    '名前': session.user_name,
    '患者ID': session.patient_id,
    '開始日時': session.started_at,
    'セッションID': session.session_id,
  }));

  const csvContent = CSVExporter.generateCSV(
    ['役割', '名前', '患者ID', '開始日時', 'セッションID'],
    data
  );

  const filename = `history_log_${new Date().toISOString().split('T')[0]}.csv`;
  await CSVExporter.downloadCSV(filename, csvContent);
};

</script>

<style scoped>
/* Add any component-specific styles here */
</style>