<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <v-card>
          <v-card-title>
            <span class="text-h4">プロンプト管理</span>
          </v-card-title>
          <v-card-text>
            <v-tabs v-model="currentTab" grow>
              <v-tab value="patient">患者AI</v-tab>
              <v-tab value="interviewer">保健師AI</v-tab>
              <v-tab value="evaluator">評価AI</v-tab>
            </v-tabs>

            <v-tabs-window v-model="currentTab">
              <v-tabs-window-item
                v-for="templateType in ['patient', 'interviewer', 'evaluator']"
                :key="templateType"
                :value="templateType"
              >
                <v-card flat>
                  <v-card-text>
                    <v-row>
                      <v-col cols="12" md="6">
                        <v-card>
                          <v-card-title>現在のプロンプト</v-card-title>
                          <v-card-text>
                            <v-alert
                              v-if="loadingActive[templateType]"
                              type="info"
                              text="読み込み中..."
                            />
                            <v-alert
                              v-else-if="!activePrompts[templateType]"
                              type="warning"
                              text="アクティブなプロンプトがありません"
                            />
                            <div v-else>
                              <div class="mb-2">
                                <v-chip
                                  color="success"
                                  size="small"
                                  class="mr-2"
                                >
                                  ID: {{ activePrompts[templateType].id }}
                                </v-chip>
                                <v-chip
                                  color="primary"
                                  size="small"
                                >
                                  v{{ activePrompts[templateType].version }}
                                </v-chip>
                              </div>
                              <div class="mb-2">
                                <strong>説明:</strong>
                                {{ activePrompts[templateType].description || '未設定' }}
                              </div>
                              <div class="mb-2">
                                <strong>プロンプト:</strong>
                                <pre class="text-caption">{{ activePrompts[templateType].prompt_text }}</pre>
                              </div>
                              <div v-if="activePrompts[templateType].message_text" class="mb-2">
                                <strong>初期メッセージ:</strong>
                                <pre class="text-caption">{{ activePrompts[templateType].message_text }}</pre>
                              </div>
                              <div class="text-caption text-medium-emphasis">
                                作成日: {{ formatDate(activePrompts[templateType].created_at) }}
                              </div>
                            </div>
                          </v-card-text>
                        </v-card>
                      </v-col>
                      <v-col cols="12" md="6">
                        <v-card>
                          <v-card-title>新しいプロンプト作成</v-card-title>
                          <v-card-text>
                            <v-form @submit.prevent="createNewPrompt(templateType)">
                              <v-textarea
                                v-model="forms[templateType].description"
                                label="説明"
                                rows="2"
                                class="mb-3"
                              />
                              <v-textarea
                                v-model="forms[templateType].prompt_text"
                                label="プロンプト"
                                rows="8"
                                required
                                class="mb-3"
                              />
                              <v-textarea
                                v-if="templateType !== 'evaluator'"
                                v-model="forms[templateType].message_text"
                                label="初期メッセージ"
                                rows="3"
                                class="mb-3"
                              />
                              <v-btn
                                type="submit"
                                color="primary"
                                :loading="creating[templateType]"
                                :disabled="!forms[templateType].prompt_text"
                              >
                                作成
                              </v-btn>
                            </v-form>
                          </v-card-text>
                        </v-card>
                      </v-col>
                    </v-row>
                    
                    <v-divider class="my-6" />
                    
                    <v-row>
                      <v-col cols="12">
                        <v-card>
                          <v-card-title>履歴・バージョン管理</v-card-title>
                          <v-card-text>
                            <v-data-table
                              :headers="tableHeaders"
                              :items="allPrompts[templateType] || []"
                              :loading="loadingAll[templateType]"
                              item-value="id"
                            >
                              <template #item.is_active="{ item }">
                                <v-chip
                                  :color="item.is_active ? 'success' : 'default'"
                                  size="small"
                                >
                                  {{ item.is_active ? 'アクティブ' : '非アクティブ' }}
                                </v-chip>
                              </template>
                              <template #item.created_at="{ item }">
                                {{ formatDate(item.created_at) }}
                              </template>
                              <template #item.actions="{ item }">
                                <v-btn
                                  v-if="!item.is_active"
                                  size="small"
                                  color="primary"
                                  variant="outlined"
                                  @click="activatePrompt(item.id, templateType)"
                                  :loading="activating[item.id]"
                                >
                                  アクティブ化
                                </v-btn>
                                <v-btn
                                  size="small"
                                  color="info"
                                  variant="text"
                                  @click="showPromptDetail(item)"
                                >
                                  詳細
                                </v-btn>
                              </template>
                            </v-data-table>
                          </v-card-text>
                        </v-card>
                      </v-col>
                    </v-row>
                  </v-card-text>
                </v-card>
              </v-tabs-window-item>
            </v-tabs-window>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 詳細表示ダイアログ -->
    <v-dialog v-model="detailDialog" max-width="800">
      <v-card v-if="selectedPrompt">
        <v-card-title>
          プロンプト詳細 (ID: {{ selectedPrompt.id }}, v{{ selectedPrompt.version }})
        </v-card-title>
        <v-card-text>
          <div class="mb-4">
            <strong>種類:</strong> {{ getTemplateTypeLabel(selectedPrompt.template_type) }}
          </div>
          <div class="mb-4">
            <strong>バージョン:</strong> v{{ selectedPrompt.version }}
          </div>
          <div class="mb-4">
            <strong>説明:</strong> {{ selectedPrompt.description || '未設定' }}
          </div>
          <div class="mb-4">
            <strong>プロンプト:</strong>
            <pre class="bg-grey-lighten-4 pa-3 rounded">{{ selectedPrompt.prompt_text }}</pre>
          </div>
          <div v-if="selectedPrompt.message_text" class="mb-4">
            <strong>初期メッセージ:</strong>
            <pre class="bg-grey-lighten-4 pa-3 rounded">{{ selectedPrompt.message_text }}</pre>
          </div>
          <div class="mb-4">
            <strong>状態:</strong>
            <v-chip :color="selectedPrompt.is_active ? 'success' : 'default'" size="small">
              {{ selectedPrompt.is_active ? 'アクティブ' : '非アクティブ' }}
            </v-chip>
          </div>
          <div class="mb-4">
            <strong>作成日:</strong> {{ formatDate(selectedPrompt.created_at) }}
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="primary" @click="detailDialog = false">閉じる</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- スナックバー -->
    <v-snackbar
      v-model="snackbar.show"
      :color="snackbar.color"
      :timeout="4000"
    >
      {{ snackbar.message }}
    </v-snackbar>
  </v-container>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue';
import { api } from '@/utils/api';
import type { PromptTemplate, PromptTemplateType } from '@/types';

const currentTab = ref<PromptTemplateType>('patient');
const detailDialog = ref(false);
const selectedPrompt = ref<PromptTemplate | null>(null);

// データ管理
const activePrompts = reactive<Record<PromptTemplateType, PromptTemplate | null>>({
  patient: null,
  interviewer: null,
  evaluator: null
});

const allPrompts = reactive<Record<PromptTemplateType, PromptTemplate[]>>({
  patient: [],
  interviewer: [],
  evaluator: []
});

// ローディング状態
const loadingActive = reactive<Record<PromptTemplateType, boolean>>({
  patient: false,
  interviewer: false,
  evaluator: false
});

const loadingAll = reactive<Record<PromptTemplateType, boolean>>({
  patient: false,
  interviewer: false,
  evaluator: false
});

const creating = reactive<Record<PromptTemplateType, boolean>>({
  patient: false,
  interviewer: false,
  evaluator: false
});

const activating = reactive<Record<number, boolean>>({});

// フォーム管理
const forms = reactive<Record<PromptTemplateType, {
  description: string;
  prompt_text: string;
  message_text: string;
}>>({
  patient: {
    description: '',
    prompt_text: '',
    message_text: ''
  },
  interviewer: {
    description: '',
    prompt_text: '',
    message_text: ''
  },
  evaluator: {
    description: '',
    prompt_text: '',
    message_text: ''
  }
});

// スナックバー
const snackbar = reactive({
  show: false,
  message: '',
  color: 'success'
});

// テーブルヘッダー
const tableHeaders = [
  { title: 'ID', key: 'id', width: '80px' },
  { title: 'バージョン', key: 'version', width: '100px' },
  { title: '説明', key: 'description' },
  { title: '状態', key: 'is_active', width: '120px' },
  { title: '作成日', key: 'created_at', width: '180px' },
  { title: 'アクション', key: 'actions', width: '200px', sortable: false }
];

// メソッド
const showSnackbar = (message: string, color: string = 'success') => {
  snackbar.message = message;
  snackbar.color = color;
  snackbar.show = true;
};

const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleString('ja-JP');
};

const getTemplateTypeLabel = (type: PromptTemplateType): string => {
  const labels = {
    patient: '患者AI',
    interviewer: '保健師AI',
    evaluator: '評価AI'
  };
  return labels[type];
};

const loadActivePrompt = async (templateType: PromptTemplateType) => {
  loadingActive[templateType] = true;
  try {
    activePrompts[templateType] = await api.getActivePrompt(templateType);
  } catch (error: any) {
    if (error.status === 404) {
      // 404エラーは正常な状態（アクティブなプロンプトが存在しない）
      activePrompts[templateType] = null;
    } else {
      console.error(`Failed to load active prompt for ${templateType}:`, error);
      activePrompts[templateType] = null;
    }
  } finally {
    loadingActive[templateType] = false;
  }
};

const loadAllPrompts = async (templateType: PromptTemplateType) => {
  loadingAll[templateType] = true;
  try {
    allPrompts[templateType] = await api.getAllPrompts(templateType);
  } catch (error) {
    console.error(`Failed to load all prompts for ${templateType}:`, error);
    allPrompts[templateType] = [];
  } finally {
    loadingAll[templateType] = false;
  }
};

const createNewPrompt = async (templateType: PromptTemplateType) => {
  creating[templateType] = true;
  try {
    await api.createPrompt({
      template_type: templateType,
      prompt_text: forms[templateType].prompt_text,
      message_text: forms[templateType].message_text || undefined,
      description: forms[templateType].description || undefined
    });
    
    // フォームをリセット
    forms[templateType] = {
      description: '',
      prompt_text: '',
      message_text: ''
    };
    
    // データを再読み込み
    await Promise.all([
      loadActivePrompt(templateType),
      loadAllPrompts(templateType)
    ]);
    
    showSnackbar('プロンプトが作成されました');
  } catch (error) {
    console.error(`Failed to create prompt for ${templateType}:`, error);
    showSnackbar('プロンプトの作成に失敗しました', 'error');
  } finally {
    creating[templateType] = false;
  }
};

const activatePrompt = async (templateId: number, templateType: PromptTemplateType) => {
  activating[templateId] = true;
  try {
    await api.activatePrompt(templateId);
    
    // データを再読み込み
    await Promise.all([
      loadActivePrompt(templateType),
      loadAllPrompts(templateType)
    ]);
    
    showSnackbar('プロンプトがアクティブになりました');
  } catch (error) {
    console.error(`Failed to activate prompt ${templateId}:`, error);
    showSnackbar('プロンプトのアクティブ化に失敗しました', 'error');
  } finally {
    activating[templateId] = false;
  }
};

const showPromptDetail = (prompt: PromptTemplate) => {
  selectedPrompt.value = prompt;
  detailDialog.value = true;
};

const loadData = async () => {
  const templateTypes: PromptTemplateType[] = ['patient', 'interviewer', 'evaluator'];
  
  for (const type of templateTypes) {
    await Promise.all([
      loadActivePrompt(type),
      loadAllPrompts(type)
    ]);
  }
};

onMounted(() => {
  loadData();
});
</script>

<style scoped>
pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 0.85em;
  line-height: 1.4;
}
</style>