<template>
  <v-container class="py-8" style="max-width: 880px">
    <!-- 判定中 -->
    <div v-if="loading" class="text-center py-12">
      <v-progress-circular indeterminate color="primary" size="48" />
      <div class="text-body-2 text-grey mt-4">
        対話内容を判定しています...
      </div>
    </div>

    <!-- エラー -->
    <v-alert v-else-if="error" type="error" variant="tonal" class="my-8">
      {{ error }}
    </v-alert>

    <!-- 結果 -->
    <template v-else-if="result">
      <h1 class="text-h5 font-weight-bold mb-1">判定結果</h1>
      <p class="text-body-2 text-grey mb-6">患者ID {{ result.patient_id }} の疫学調査</p>

      <!-- スコアサマリ -->
      <v-card variant="outlined" class="mb-6">
        <v-card-text>
          <div class="d-flex align-center justify-space-between flex-wrap ga-6">
            <div>
              <div class="text-caption text-grey">項目聴取率</div>
              <div class="text-h3 font-weight-bold" :class="scoreColorClass">
                {{ (result.score * 100).toFixed(1) }}<span class="text-h6">%</span>
              </div>
              <div class="text-caption text-grey mt-1">
                聴取できた項目数 ÷ 全項目数
              </div>
            </div>
            <v-divider vertical class="d-none d-sm-flex" />
            <div>
              <div class="text-body-2">
                聴取項目数：<strong>{{ result.collected_item_count }}</strong>
                / {{ result.total_item_count }}
              </div>
              <div class="text-body-2 mt-1">
                対話量：<strong>{{ result.message_count }}</strong> メッセージ
                ／ 質問数：<strong>{{ result.question_count }}</strong>
              </div>
              <div class="text-body-2 mt-1" v-if="result.correct_per_10_questions != null">
                10質問あたりの聴取項目数：<strong>{{ result.correct_per_10_questions.toFixed(2) }}</strong>
              </div>
            </div>
          </div>
        </v-card-text>
      </v-card>

      <!-- 聞き漏らした高リスク項目 -->
      <v-card variant="outlined" class="mb-6" v-if="missedHighRisk.length">
        <v-card-title class="text-subtitle-1 text-red-darken-2">
          聞き漏らした重要項目
        </v-card-title>
        <v-list density="comfortable">
          <v-list-item v-for="item in missedHighRisk" :key="item.instance_id">
            <template #prepend>
              <v-icon color="red-darken-2" size="small">mdi-alert-circle-outline</v-icon>
            </template>
            <v-list-item-title class="text-body-2" style="white-space: normal">
              {{ item.description }}
            </v-list-item-title>
            <v-list-item-subtitle>
              {{ item.item_type_code }} ／
              リスク {{ item.risk_score != null ? item.risk_score.toFixed(2) : '—' }}
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
      </v-card>

      <!-- 全項目テーブル -->
      <v-card variant="outlined" class="mb-6">
        <v-card-title class="text-subtitle-1">全項目の判定</v-card-title>
        <v-data-table
          :headers="itemHeaders"
          :items="result.items"
          density="compact"
          :items-per-page="20"
        >
          <template #item.risk_score="{ item }">
            <span v-if="item.risk_score != null">{{ item.risk_score.toFixed(3) }}</span>
            <span v-else>—</span>
          </template>
          <template #item.collected="{ item }">
            <v-icon v-if="item.collected" color="success" size="small">mdi-check-circle</v-icon>
            <v-icon v-else color="grey-lighten-1" size="small">mdi-close-circle-outline</v-icon>
          </template>
        </v-data-table>
      </v-card>

      <v-btn color="primary" variant="tonal" @click="returnHome">
        <v-icon start>mdi-arrow-left</v-icon>
        トップに戻る
      </v-btn>
    </template>
  </v-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { irtApi, type IRTSessionResult } from '@/utils/irtApi';

const route = useRoute();
const router = useRouter();

const sessionId = computed(() => String(route.params.sessionId || ''));
const loading = ref(true);
const error = ref('');
const result = ref<IRTSessionResult | null>(null);

const itemHeaders = [
  { title: '項目', key: 'item_type_code', width: '90px' },
  { title: '内容', key: 'description' },
  { title: 'リスク', key: 'risk_score', width: '90px' },
  { title: '聴取', key: 'collected', width: '70px' },
];

const scoreColorClass = computed(() => {
  const s = result.value?.score ?? 0;
  if (s >= 0.7) return 'text-success';
  if (s >= 0.4) return 'text-orange-darken-2';
  return 'text-red-darken-2';
});

const missedHighRisk = computed(() => {
  if (!result.value) return [];
  return result.value.items
    .filter((it) => !it.collected && (it.risk_score ?? 0) >= 0.5)
    .slice(0, 10);
});

const load = async () => {
  loading.value = true;
  error.value = '';
  try {
    result.value = await irtApi.getSessionResult(sessionId.value);
  } catch (e: any) {
    error.value = `判定結果の取得に失敗しました：${e?.message ?? '不明なエラー'}`;
  } finally {
    loading.value = false;
  }
};

const returnHome = () => {
  localStorage.removeItem('activeSession');
  router.push('/');
};

onMounted(load);
</script>
