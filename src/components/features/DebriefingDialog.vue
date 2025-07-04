<template>
  <v-dialog v-model="localDialog" persistent max-width="80vw" scrollable>
    <v-card v-if="debriefingData">
      <v-toolbar color="primary" density="compact">
        <v-toolbar-title>評価レポート</v-toolbar-title>
        <v-spacer></v-spacer>
        <v-btn icon @click="localDialog = false"><v-icon>mdi-close</v-icon></v-btn>
      </v-toolbar>
      <v-card-text class="pa-md-6 pa-4">
        <!-- エラー表示 -->
        <v-alert v-if="debriefingData.error" type="error" dense>
          {{ debriefingData.error }}
        </v-alert>

        <div v-else>
          <!-- 総合得点 -->
          <v-card class="mb-4" outlined>
            <v-card-title class="text-h6 font-weight-bold d-flex align-center">
              <v-icon color="amber" class="mr-2">mdi-star-circle</v-icon>
              総合得点
            </v-card-title>
            <v-card-text>
              <v-progress-linear :model-value="debriefingData.overall_score" color="primary" height="25" rounded>
                <strong class="text-white">{{ debriefingData.overall_score }} / 100 点</strong>
              </v-progress-linear>
            </v-card-text>
          </v-card>

          <!-- 各評価項目 -->
          <v-card class="mb-4" outlined>
            <v-card-text>
              <div class="mb-4">
                <div class="font-weight-bold mb-1">1. 感染に関わる情報の聴取割合</div>
                <p class="text-body-1">{{ debriefingData.information_retrieval_ratio }}</p>
              </div>
              <v-divider></v-divider>
              <div class="my-4">
                <div class="font-weight-bold mb-1">2. 回答した情報の質</div>
                <p class="text-body-1">{{ debriefingData.information_quality }}</p>
              </div>
              <v-divider></v-divider>
              <div class="mt-4">
                <div class="font-weight-bold mb-2">3. 総評</div>
                <p class="text-body-1">{{ debriefingData.overall_comment }}</p>
              </div>
            </v-card-text>
          </v-card>

          <!-- ミクロな評価 -->
          <div>
            <div class="text-h6 font-weight-bold mb-2 d-flex align-center">
              <v-icon color="blue" class="mr-2">mdi-comment-quote-outline</v-icon>
              個別の発言へのフィードバック
            </div>
            <v-list lines="three" class="bg-transparent">
              <v-list-item
                v-for="(item, i) in debriefingData.micro_evaluations"
                :key="i"
                class="mb-2"
                border
                rounded
              >
                <template v-slot:prepend>
                  <v-avatar 
                    size="40" 
                    :class="evaluationSymbolColor(item.evaluation_symbol)"
                    class="mr-3"
                  >
                    <span class="font-weight-bold text-white">
                      {{ item.evaluation_symbol }}
                    </span>
                  </v-avatar>
                </template>
                <v-list-item-title class="text-wrap font-italic mb-2">「{{ item.utterance }}」</v-list-item-title>
                <v-list-item-subtitle class="text-wrap" style="line-height: 1.7;">
                  {{ item.advice }}
                </v-list-item-subtitle>
              </v-list-item>
            </v-list>
          </div>
        </div>
      </v-card-text>
      <v-divider></v-divider>
      <v-card-actions class="justify-center pa-4">
        <v-btn color="primary" size="large" @click="$emit('start-new-session')">新しいセッションを開始する</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
  <v-overlay v-model="isLoading" class="align-center justify-center" persistent>
    <v-progress-circular indeterminate size="64" color="primary"></v-progress-circular>
    <div class="text-center mt-4">評価を生成しています...</div>
  </v-overlay>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  modelValue: Boolean,
  debriefingData: Object,
  loading: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['update:modelValue', 'start-new-session']);

const localDialog = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
});

const isLoading = computed(() => props.loading);

const evaluationSymbolColor = (symbol) => {
    switch (symbol) {
        case '◎': return 'bg-teal';
        case '○': return 'bg-indigo';
        case '△': return 'bg-orange';
        case '✕': return 'bg-red';
        default: return 'bg-grey-lighten-1';
    }
};
</script>

<style scoped>
.border {
  border: 1px solid #e0e0e0;
}
</style>