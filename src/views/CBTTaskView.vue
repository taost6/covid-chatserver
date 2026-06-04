<template>
  <v-container class="py-8" style="max-width: 720px">
    <v-btn variant="text" size="small" prepend-icon="mdi-arrow-left" class="mb-4" @click="backToDashboard">
      ダッシュボードに戻る
    </v-btn>

    <v-card variant="outlined">
      <v-card-title class="text-h6">疫学調査タスク</v-card-title>
      <v-card-text>
        <div class="text-body-2 mb-4">
          このタスクでは、<strong>患者ID {{ patientId }}</strong> の疫学調査を行います。
          保健師として患者AIと対話し、感染リスクの把握に必要な情報を聴取してください。
        </div>

        <v-alert type="info" variant="tonal" density="comfortable" class="mb-4">
          「疫学調査を開始する」を押すと対話画面に移動し、保健師ロール・患者ID {{ patientId }} で
          調査が始まります。対話を終えて評価をリクエストすると、自動で採点され結果画面が表示されます。
        </v-alert>

        <v-btn color="primary" size="large" block @click="openChat">
          疫学調査を開始する
        </v-btn>
      </v-card-text>
    </v-card>
  </v-container>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const route = useRoute();
const router = useRouter();

const token = computed(() => String(route.params.token || ''));
const patientId = computed(() => String(route.params.patientId || ''));

const backToDashboard = () => {
  router.push({ name: 'cbt-dashboard', params: { token: token.value } });
};

const openChat = () => {
  // 前のタスクのセッション情報を破棄してクリーンに開始する
  localStorage.removeItem('activeSession');
  sessionStorage.removeItem('cbt_session_id');
  // CBT文脈を保存し、対話画面へ。ChatViewが保健師ロール・該当患者で自動登録する。
  sessionStorage.setItem('cbt_token', token.value);
  sessionStorage.setItem('cbt_patient_id', patientId.value);
  router.push({ name: 'chat' });
};
</script>
