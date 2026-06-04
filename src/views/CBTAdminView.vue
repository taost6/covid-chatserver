<template>
  <v-container class="py-8" style="max-width: 1100px">
    <h1 class="text-h5 font-weight-bold mb-1">CBT 管理コンソール</h1>
    <p class="text-body-2 text-grey mb-6">
      被験者向けアクセスURLの発行と、進捗の俯瞰を行います。
    </p>

    <!-- 管理者キー -->
    <v-card variant="outlined" class="mb-6">
      <v-card-text>
        <v-text-field
          v-model="adminKey"
          label="管理者キー（X-Admin-Key）"
          type="password"
          density="comfortable"
          hide-details
          placeholder="サーバーで CBT_ADMIN_KEY が未設定の場合は空欄で可"
        />
      </v-card-text>
    </v-card>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4" closable @click:close="error = ''">
      {{ error }}
    </v-alert>

    <!-- URL発行 -->
    <v-card variant="outlined" class="mb-6">
      <v-card-title class="text-subtitle-1">URLを発行</v-card-title>
      <v-card-text>
        <div class="d-flex align-center ga-4">
          <v-text-field
            v-model.number="issueCount"
            label="発行数"
            type="number"
            density="comfortable"
            hide-details
            style="max-width: 160px"
            :min="1"
            :max="500"
          />
          <v-btn color="primary" :loading="issuing" @click="issueTokens">
            発行する
          </v-btn>
        </div>
        <div class="text-caption text-grey mt-2">
          発行後、下の一覧の「ラベル」欄で各URLに名前を付けられます。
        </div>
      </v-card-text>
    </v-card>

    <!-- トークン一覧 -->
    <v-card variant="outlined">
      <v-card-title class="text-subtitle-1 d-flex align-center">
        発行済みURL一覧
        <v-spacer />
        <v-btn variant="text" size="small" :loading="loading" @click="loadTokens">
          再読み込み
        </v-btn>
        <v-btn variant="text" size="small" :href="csvUrl" target="_blank">
          CSVエクスポート
        </v-btn>
      </v-card-title>
      <v-data-table
        :headers="headers"
        :items="tokens"
        density="comfortable"
        :items-per-page="25"
        :loading="loading"
        show-expand
        v-model:expanded="expandedTokenIds"
        item-value="id"
        @update:expanded="onExpand"
      >
        <template #item.label="{ item }">
          <v-text-field
            v-model="item.label"
            density="compact"
            variant="plain"
            hide-details
            placeholder="（未設定）"
            style="min-width: 120px"
            @blur="saveLabel(item)"
            @keyup.enter="saveLabel(item)"
          />
        </template>
        <template #item.url="{ item }">
          <div class="d-flex align-center">
            <code class="cbt-url">{{ trainingUrl(item.token) }}</code>
            <v-btn
              icon="mdi-content-copy"
              size="x-small"
              variant="text"
              @click="copyUrl(item.token)"
            />
          </div>
        </template>
        <template #item.is_active="{ item }">
          <v-chip :color="item.is_active ? 'success' : 'grey'" size="small" variant="tonal">
            {{ item.is_active ? '有効' : '無効' }}
          </v-chip>
        </template>
        <template #item.progress="{ item }">
          {{ item.completed_count }} 完了 / {{ item.total_count }} 着手
        </template>
        <template #item.last_seen_at="{ item }">
          <span v-if="item.last_seen_at">{{ formatDate(item.last_seen_at) }}</span>
          <span v-else class="text-grey">未アクセス</span>
        </template>
        <template #item.actions="{ item }">
          <v-btn
            v-if="item.is_active"
            size="x-small"
            color="error"
            variant="tonal"
            @click="deactivate(item)"
          >
            無効化
          </v-btn>
        </template>

        <template #expanded-row="{ columns, item }">
          <tr>
            <td :colspan="columns.length" class="pa-4 bg-grey-lighten-5">
              <div v-if="detailLoading[item.id]" class="text-center py-4">
                <v-progress-circular indeterminate color="primary" size="28" />
              </div>
              <template v-else-if="detailMap[item.id]">
                <!-- サマリ -->
                <div class="d-flex align-center ga-6 flex-wrap mb-3">
                  <v-chip color="info" variant="tonal" size="small">
                    完了：{{ detailMap[item.id].completed_count }} / {{ detailMap[item.id].total_count }}
                  </v-chip>
                  <v-chip
                    v-if="detailMap[item.id].average_score != null"
                    color="primary"
                    variant="tonal"
                    size="small"
                  >
                    平均聴取率：{{ (detailMap[item.id].average_score * 100).toFixed(1) }}%
                  </v-chip>
                  <span class="text-caption text-grey">
                    発行：{{ formatDate(item.created_at) }}
                  </span>
                </div>

                <!-- 課題一覧 -->
                <v-table density="compact" class="cbt-detail-table">
                  <thead>
                    <tr>
                      <th>患者ID</th>
                      <th>状態</th>
                      <th>項目聴取率</th>
                      <th>開始日時</th>
                      <th>完了日時</th>
                      <th>セッション</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="task in detailMap[item.id].progress" :key="task.progress_id">
                      <td>{{ task.patient_id }}</td>
                      <td>
                        <v-chip
                          :color="task.status === 'completed' ? 'success' : 'orange'"
                          size="x-small"
                          variant="tonal"
                        >
                          {{ task.status === 'completed' ? '完了' : '進行中' }}
                        </v-chip>
                      </td>
                      <td>
                        <span v-if="task.score != null">
                          {{ (task.score * 100).toFixed(1) }}%
                        </span>
                        <span v-else class="text-grey">—</span>
                      </td>
                      <td>{{ task.started_at ? formatDate(task.started_at) : '—' }}</td>
                      <td>{{ task.completed_at ? formatDate(task.completed_at) : '—' }}</td>
                      <td>
                        <router-link
                          v-if="task.session_id"
                          :to="{ name: 'history-detail', params: { sessionId: task.session_id } }"
                          class="text-caption"
                          target="_blank"
                        >
                          ログ表示
                        </router-link>
                        <span v-else class="text-grey text-caption">—</span>
                      </td>
                    </tr>
                    <tr v-if="!detailMap[item.id].progress.length">
                      <td colspan="6" class="text-center text-grey py-2">
                        まだ課題に取り組んでいません
                      </td>
                    </tr>
                  </tbody>
                </v-table>
              </template>
              <div v-else class="text-grey">読み込みに失敗しました。</div>
            </td>
          </tr>
        </template>
      </v-data-table>
    </v-card>

    <v-snackbar v-model="snackbar" :timeout="2000" color="success">
      {{ snackbarText }}
    </v-snackbar>
  </v-container>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue';
import { cbtApi, type CBTAdminToken, type CBTAdminTokenDetail } from '@/utils/cbtApi';

const adminKey = ref('');
const issueCount = ref(1);
const tokens = ref<CBTAdminToken[]>([]);
const loading = ref(false);
const issuing = ref(false);
const error = ref('');
const snackbar = ref(false);
const snackbarText = ref('');
const expandedTokenIds = ref<number[]>([]);
const detailMap = reactive<Record<number, CBTAdminTokenDetail>>({});
const detailLoading = reactive<Record<number, boolean>>({});

const csvUrl = cbtApi.exportCsvUrl();

const headers = [
  { title: 'ラベル', key: 'label', width: '140px' },
  { title: 'アクセスURL', key: 'url' },
  { title: '状態', key: 'is_active', width: '80px' },
  { title: '進捗', key: 'progress', width: '140px' },
  { title: '最終アクセス', key: 'last_seen_at', width: '150px' },
  { title: '', key: 'actions', width: '80px', sortable: false },
  { title: '', key: 'data-table-expand', width: '40px' },
];

const trainingUrl = (token: string): string => {
  return `${window.location.origin}/cbt/t/${token}`;
};

const formatDate = (iso: string): string => {
  return new Date(iso).toLocaleString('ja-JP', { dateStyle: 'short', timeStyle: 'short' });
};

const showSnack = (text: string) => {
  snackbarText.value = text;
  snackbar.value = true;
};

const loadTokens = async () => {
  loading.value = true;
  error.value = '';
  try {
    tokens.value = await cbtApi.listTokens(adminKey.value);
  } catch (e: any) {
    if (e?.status === 403) error.value = '管理者キーが正しくありません。';
    else error.value = `読み込みに失敗しました：${e?.message ?? '不明なエラー'}`;
  } finally {
    loading.value = false;
  }
};

const issueTokens = async () => {
  if (issueCount.value < 1) return;
  issuing.value = true;
  error.value = '';
  try {
    await cbtApi.issueTokens(adminKey.value, issueCount.value);
    showSnack(`${issueCount.value} 件のURLを発行しました`);
    await loadTokens();
  } catch (e: any) {
    if (e?.status === 403) error.value = '管理者キーが正しくありません。';
    else error.value = `発行に失敗しました：${e?.message ?? '不明なエラー'}`;
  } finally {
    issuing.value = false;
  }
};

const onExpand = async (expandedIds: number[]) => {
  // 新たに展開されたトークンの詳細を取得する
  for (const tokenId of expandedIds) {
    if (detailMap[tokenId] || detailLoading[tokenId]) continue;
    detailLoading[tokenId] = true;
    try {
      detailMap[tokenId] = await cbtApi.getTokenDetail(adminKey.value, tokenId);
    } catch (e: any) {
      if (e?.status === 403) error.value = '管理者キーが正しくありません。';
      else error.value = `詳細の取得に失敗しました：${e?.message ?? '不明なエラー'}`;
    } finally {
      detailLoading[tokenId] = false;
    }
  }
};

const saveLabel = async (item: CBTAdminToken) => {
  try {
    await cbtApi.updateTokenLabel(adminKey.value, item.id, item.label ?? '');
  } catch (e: any) {
    if (e?.status === 403) error.value = '管理者キーが正しくありません。';
    else error.value = `ラベルの更新に失敗しました：${e?.message ?? '不明なエラー'}`;
  }
};

const deactivate = async (item: CBTAdminToken) => {
  try {
    await cbtApi.deactivateToken(adminKey.value, item.id);
    showSnack('URLを無効化しました');
    await loadTokens();
  } catch (e: any) {
    error.value = `無効化に失敗しました：${e?.message ?? '不明なエラー'}`;
  }
};

const copyUrl = async (token: string) => {
  try {
    await navigator.clipboard.writeText(trainingUrl(token));
    showSnack('URLをコピーしました');
  } catch {
    error.value = 'クリップボードへのコピーに失敗しました';
  }
};

onMounted(loadTokens);
</script>

<style scoped>
.cbt-url {
  font-size: 0.78rem;
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
  word-break: break-all;
}
.cbt-detail-table th,
.cbt-detail-table td {
  white-space: nowrap;
  font-size: 0.85rem;
}
</style>
