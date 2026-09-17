<template>
  <v-card v-if="result.assessment_version" variant="outlined" class="mb-6">
    <v-card-title class="text-subtitle-1">判定の根拠</v-card-title>
    <v-card-text>
      <v-btn variant="tonal" size="small" class="mb-3" @click="download">判定と集計をCSV保存</v-btn>
      <v-expansion-panels variant="accordion">
        <v-expansion-panel v-for="item in result.items" :key="item.instance_id">
          <v-expansion-panel-title>{{ item.item_type_code }}：{{ gradeLabel(item.grade, item.collected) }}</v-expansion-panel-title>
          <v-expansion-panel-text>
            <p style="white-space: pre-wrap">{{ item.description }}</p>
            <p class="mt-3">{{ item.reason }}</p>
            <p class="text-caption mt-2">根拠発言ID：質問・確認 {{ item.question_message_ids?.join(', ') || 'なし' }}
              ／ 患者回答 {{ item.answer_message_ids?.join(', ') || 'なし' }}</p>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </v-card-text>
  </v-card>
</template>
<script setup lang="ts">
import { CSVExporter } from '@/utils/csvExport';
import { gradeLabel, type AssessmentMetrics, type AssessmentEvidence } from '@/types/assessment';
const props = defineProps<{ result: AssessmentMetrics & {
  patient_id: string; score: number | null; message_count: number; question_count: number;
  items: (AssessmentEvidence & { instance_id: number; item_type_code: string; description: string | null; collected: boolean })[];
} }>();
const download = () => {
  const r = props.result;
  const rows = [
    ['患者ID', '評価版', '調査日', '項目ID', '項目', '判定', '理由', '質問・確認ID', '回答ID',
      '表示発話数', '実質対話数', '質問行為数', '確認行為数', '説明行為数', '聴取率'],
    ...r.items.map(i => [r.patient_id, r.assessment_version, r.interview_date, i.instance_id,
      i.item_type_code, gradeLabel(i.grade, i.collected), i.reason,
      i.question_message_ids?.join(' '), i.answer_message_ids?.join(' '), r.display_message_count,
      r.message_count, r.question_count, r.confirmation_count, r.explanation_count, r.score]),
  ];
  const headers = rows[0].map(String);
  const data = rows.slice(1).map(row => Object.fromEntries(row.map((value, index) => {
    let cell = String(value ?? '');
    if (/^[=+\-@\t\r]/.test(cell)) cell = "'" + cell;
    return [headers[index], cell];
  })));
  CSVExporter.downloadCSV(`assessment_${r.patient_id}_${r.assessment_version}.csv`,
    CSVExporter.generateCSV(headers, data), 'UTF8');
};
</script>
