<template>
  <div class="text-body-2">
    <template v-if="result.assessment_version">
      <div class="text-caption">結果形式 {{ result.assessment_version }} ／
        採点プロンプト v{{ result.evaluator_prompt_version ?? '不明' }} ／ {{ result.evaluator_model ?? '不明' }}</div>
      <div>○ {{ result.collected_item_count }} ／ △ {{ result.incidental_item_count }} ／
        × {{ result.missing_item_count }} ／ 保留 {{ result.pending_item_count }}</div>
      <div class="mt-1">表示発話数 {{ result.display_message_count }}
        （初期挨拶 {{ result.initial_message_count }} を含む）</div>
      <div>実質対話数 {{ result.message_count }} ／ 保健師発話 {{ result.nurse_turn_count }}</div>
      <div class="mt-1">質問 {{ result.question_count }} ／ 確認 {{ result.confirmation_count }} ／
        説明 {{ result.explanation_count }} ／ その他 {{ result.other_act_count }}</div>
      <div class="text-caption text-grey">質問・確認・説明は発話内の意味単位で数えています。発話数とは異なります。</div>
      <div v-if="result.pending_item_count" class="text-orange-darken-3 mt-2">
        判定保留の項目があるため、聴取率は未確定です。
      </div>
      <div v-if="result.interview_date" class="mt-1">調査日：{{ result.interview_date }}</div>
    </template>
    <template v-else>
      <div>旧判定の聴取項目数：{{ result.collected_item_count }} / {{ result.total_item_count }}</div>
      <div>対話量（初期挨拶を除く）：{{ result.message_count }}</div>
      <div>旧質問指標（疑問符の数）：{{ result.question_count }}</div>
      <div class="text-caption text-grey">旧判定から、意図を持って聴取したかは判断できません。</div>
    </template>
  </div>
</template>
<script setup lang="ts">
import type { AssessmentMetrics } from '@/types/assessment';
defineProps<{ result: AssessmentMetrics & {
  collected_item_count: number; total_item_count: number; message_count: number;
  nurse_turn_count: number; question_count: number;
} }>();
</script>
