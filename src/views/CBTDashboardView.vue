<template>
  <v-container class="cbt-dashboard py-8" style="max-width: 880px">
    <!-- ローディング -->
    <div v-if="loading" class="text-center py-12">
      <v-progress-circular indeterminate color="primary" size="48" />
      <div class="text-body-2 text-grey mt-4">読み込み中...</div>
    </div>

    <!-- エラー -->
    <v-alert v-else-if="error" type="error" variant="tonal" class="my-8">
      {{ error }}
    </v-alert>

    <!-- 本体 -->
    <template v-else-if="info">
      <div class="d-flex align-center mb-2">
        <h1 class="text-h5 font-weight-bold">疫学調査シミュレータ―（CBTモード）</h1>
        <v-chip v-if="info.label" class="ml-3" size="small" color="primary" variant="tonal">
          {{ info.label }}
        </v-chip>
      </div>
      <p class="text-body-2 text-grey mb-6">
        疫学調査の課題に取り組み、保健師としての聴取能力を測定します。
      </p>

      <!-- 進捗サマリ -->
      <v-card variant="outlined" class="mb-6">
        <v-card-text>
          <div class="d-flex align-center justify-space-between flex-wrap ga-4">
            <div>
              <div class="text-caption text-grey">完了した課題</div>
              <div class="text-h4 font-weight-bold">
                {{ info.completed_count }}
                <span class="text-body-1 text-grey">/ {{ nextTask?.total_count ?? '—' }}</span>
              </div>
            </div>
            <v-progress-circular
              :model-value="completionRate"
              :size="72"
              :width="8"
              color="primary"
            >
              {{ completionRate }}%
            </v-progress-circular>
          </div>
        </v-card-text>
      </v-card>

      <!-- 次のタスク -->
      <v-card variant="outlined" class="mb-6">
        <v-card-title class="text-subtitle-1">次のタスク</v-card-title>
        <v-card-text>
          <template v-if="info.active_task">
            <v-alert type="info" variant="tonal" density="comfortable" class="mb-3">
              進行中の課題があります（患者ID: {{ info.active_task.patient_id }}）。
            </v-alert>
            <v-btn color="primary" size="large" @click="resumeTask">
              課題を再開する
            </v-btn>
          </template>
          <template v-else-if="nextTask?.all_completed">
            <v-alert type="success" variant="tonal" density="comfortable">
              すべての課題が完了しました。お疲れさまでした。
            </v-alert>
          </template>
          <template v-else>
            <div class="text-body-2 mb-3">
              次の課題：患者ID <strong>{{ nextTask?.next_patient_id }}</strong>
            </div>
            <v-btn color="primary" size="large" :loading="starting" @click="startNextTask">
              次のタスクを開始する
            </v-btn>
          </template>
        </v-card-text>
      </v-card>

      <!-- 進捗履歴 -->
      <v-card variant="outlined">
        <v-card-title class="text-subtitle-1">これまでの記録</v-card-title>
        <v-data-table
          :headers="progressHeaders"
          :items="info.progress"
          density="comfortable"
          :items-per-page="10"
        >
          <template #item.status="{ item }">
            <v-chip
              :color="item.status === 'completed' ? 'success' : 'orange'"
              size="small"
              variant="tonal"
            >
              {{ item.status === 'completed' ? '完了' : '進行中' }}
            </v-chip>
          </template>
          <template #item.score="{ item }">
            <span v-if="item.score != null">{{ (item.score * 100).toFixed(1) }}%</span>
            <span v-else class="text-grey">—</span>
          </template>
          <template #item.ability_theta="{ item }">
            <span v-if="item.ability_theta != null">{{ item.ability_theta.toFixed(2) }}</span>
            <span v-else class="text-grey">—</span>
          </template>
          <template #item.completed_at="{ item }">
            <span v-if="item.completed_at">{{ formatDate(item.completed_at) }}</span>
            <span v-else class="text-grey">—</span>
          </template>
        </v-data-table>
      </v-card>
    </template>
  </v-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { cbtApi, type CBTTokenInfo, type CBTNextTask } from '@/utils/cbtApi';

const route = useRoute();
const router = useRouter();

const token = computed(() => String(route.params.token || ''));
const loading = ref(true);
const error = ref('');
const starting = ref(false);
const info = ref<CBTTokenInfo | null>(null);
const nextTask = ref<CBTNextTask | null>(null);

const progressHeaders = [
  { title: '患者ID', key: 'patient_id', width: '90px' },
  { title: '状態', key: 'status', width: '100px' },
  { title: '項目聴取率', key: 'score', width: '130px' },
  { title: '能力推定値 θ̂', key: 'ability_theta', width: '150px' },
  { title: '完了日時', key: 'completed_at' },
];

const completionRate = computed(() => {
  const total = nextTask.value?.total_count ?? 0;
  if (!total) return 0;
  return Math.round(((info.value?.completed_count ?? 0) / total) * 100);
});

const formatDate = (iso: string): string => {
  const d = new Date(iso);
  return d.toLocaleString('ja-JP', { dateStyle: 'short', timeStyle: 'short' });
};


const load = async () => {
  loading.value = true;
  error.value = '';
  try {
    info.value = await cbtApi.getTokenInfo(token.value);
    nextTask.value = await cbtApi.getNextTask(token.value);
  } catch (e: any) {
    if (e?.status === 404) error.value = 'このURLは無効です。管理者にお問い合わせください。';
    else if (e?.status === 403) error.value = 'このURLは無効化されています。';
    else error.value = `読み込みに失敗しました：${e?.message ?? '不明なエラー'}`;
  } finally {
    loading.value = false;
  }
};

const startNextTask = async () => {
  if (!nextTask.value?.next_patient_id) return;
  starting.value = true;
  try {
    const patientId = nextTask.value.next_patient_id;
    await cbtApi.startTask(token.value, patientId);
    goToTask(patientId);
  } catch (e: any) {
    error.value = `課題の開始に失敗しました：${e?.message ?? '不明なエラー'}`;
  } finally {
    starting.value = false;
  }
};

const resumeTask = () => {
  if (info.value?.active_task) {
    goToTask(info.value.active_task.patient_id);
  }
};

const goToTask = (patientId: string) => {
  router.push({
    name: 'cbt-task',
    params: { token: token.value, patientId },
  });
};

onMounted(load);
</script>

<style scoped>
/* テーブル見出しが途中で改行されないようにする */
.cbt-dashboard :deep(.v-data-table-header__content),
.cbt-dashboard :deep(th) {
  white-space: nowrap;
}
</style>
