<template>
  <v-container fluid>
    <v-row>
      <v-col cols="12">
        <v-card>
          <v-card-title>
            <span class="text-h4">IRT項目管理</span>
          </v-card-title>
          <v-card-text>
            <v-tabs v-model="currentTab" grow>
              <v-tab value="item-types">項目タイプ一覧</v-tab>
              <v-tab value="patient-instances">患者インスタンス</v-tab>
            </v-tabs>

            <v-tabs-window v-model="currentTab">
              <!-- タブ1: 項目タイプ一覧 -->
              <v-tabs-window-item value="item-types">
                <v-card flat>
                  <v-card-text>
                    <!-- カテゴリフィルタ -->
                    <div class="mb-4">
                      <v-chip-group v-model="selectedCategory" selected-class="text-primary">
                        <v-chip value="" variant="outlined">全て</v-chip>
                        <v-chip
                          v-for="cat in categories"
                          :key="cat.value"
                          :value="cat.value"
                          variant="outlined"
                        >
                          {{ cat.label }}
                        </v-chip>
                      </v-chip-group>
                    </div>

                    <!-- 項目タイプテーブル -->
                    <v-data-table
                      :headers="itemTypeHeaders"
                      :items="filteredItemTypes"
                      :loading="loadingItemTypes"
                      item-value="id"
                      hover
                      density="comfortable"
                    >
                      <template #item.category="{ item }">
                        <v-chip
                          :color="categoryColor(item.category)"
                          size="small"
                          variant="tonal"
                        >
                          {{ item.category }}
                        </v-chip>
                      </template>
                      <template #item.pdf_priority="{ item }">
                        <span v-if="item.pdf_priority" :class="priorityClass(item.pdf_priority)">
                          {{ item.pdf_priority }}
                        </span>
                      </template>
                      <template #item.status="{ item }">
                        <v-chip
                          :color="item.status === 'active' ? 'success' : item.status === 'candidate' ? 'warning' : 'default'"
                          size="small"
                        >
                          {{ item.status }}
                        </v-chip>
                      </template>
                      <template #item.actions="{ item }">
                        <v-btn
                          size="small"
                          color="info"
                          variant="text"
                          @click="showItemTypeDetail(item)"
                        >
                          詳細
                        </v-btn>
                      </template>
                    </v-data-table>
                  </v-card-text>
                </v-card>
              </v-tabs-window-item>

              <!-- タブ2: 患者インスタンス -->
              <v-tabs-window-item value="patient-instances">
                <v-card flat>
                  <v-card-text>
                    <v-row>
                      <!-- 患者選択 + インスタンス一覧 -->
                      <v-col cols="12" md="8">
                        <v-card>
                          <v-card-title>
                            <v-row align="center" no-gutters>
                              <v-col cols="auto" class="mr-4">インスタンス一覧</v-col>
                              <v-col cols="4">
                                <v-select
                                  v-model="selectedPatientId"
                                  :items="patientIdOptions"
                                  label="患者ID"
                                  density="compact"
                                  hide-details
                                  @update:model-value="loadPatientInstances"
                                />
                              </v-col>
                              <v-spacer />
                              <v-col cols="auto">
                                <v-chip v-if="patientInstances.length > 0" color="primary" size="small">
                                  {{ patientInstances.length }} 件
                                </v-chip>
                              </v-col>
                            </v-row>
                          </v-card-title>
                          <v-card-text>
                            <v-alert
                              v-if="!selectedPatientId"
                              type="info"
                              text="患者IDを選択してください"
                              class="mb-4"
                            />
                            <v-data-table
                              v-else
                              :headers="instanceHeaders"
                              :items="patientInstances"
                              :loading="loadingInstances"
                              item-value="id"
                              hover
                              density="comfortable"
                            >
                              <template #item.item_type_code="{ item }">
                                <v-chip
                                  :color="categoryColor(item.item_type_code.split('-')[0])"
                                  size="small"
                                  variant="tonal"
                                >
                                  {{ item.item_type_code }}-{{ circledNumber(item.instance_number) }}
                                </v-chip>
                              </template>
                              <template #item.is_detectable="{ item }">
                                <v-icon
                                  :color="item.is_detectable ? 'success' : 'grey'"
                                  size="small"
                                >
                                  {{ item.is_detectable ? 'mdi-check-circle' : 'mdi-close-circle' }}
                                </v-icon>
                              </template>
                              <template #item.scene_category="{ item }">
                                <v-chip v-if="item.scene_category" size="x-small" variant="outlined">
                                  {{ item.scene_category }}
                                </v-chip>
                              </template>
                              <template #item.actions="{ item }">
                                <v-btn
                                  size="small"
                                  color="info"
                                  variant="text"
                                  @click="showInstanceDetail(item)"
                                >
                                  詳細
                                </v-btn>
                              </template>
                            </v-data-table>
                          </v-card-text>
                        </v-card>
                      </v-col>

                      <!-- 新規インスタンス追加フォーム -->
                      <v-col cols="12" md="4">
                        <v-card>
                          <v-card-title>インスタンス追加</v-card-title>
                          <v-card-text>
                            <v-alert
                              v-if="!selectedPatientId"
                              type="info"
                              text="先に患者IDを選択してください"
                              density="compact"
                              class="mb-3"
                            />
                            <v-form
                              v-else
                              @submit.prevent="createInstance"
                            >
                              <v-select
                                v-model="instanceForm.item_type_code"
                                :items="itemTypeOptions"
                                label="項目タイプ"
                                density="compact"
                                class="mb-2"
                                required
                              />
                              <v-text-field
                                v-model.number="instanceForm.instance_number"
                                label="インスタンス番号"
                                type="number"
                                min="1"
                                density="compact"
                                class="mb-2"
                                required
                              />
                              <v-text-field
                                v-model="instanceForm.date"
                                label="日付 (例: 2022-04-10)"
                                density="compact"
                                class="mb-2"
                              />
                              <v-textarea
                                v-model="instanceForm.description"
                                label="説明"
                                rows="3"
                                density="compact"
                                class="mb-2"
                              />
                              <v-select
                                v-model="instanceForm.scene_category"
                                :items="sceneCategories"
                                label="場面カテゴリ"
                                density="compact"
                                clearable
                                class="mb-2"
                              />
                              <v-checkbox
                                v-model="instanceForm.is_detectable"
                                label="検出可能"
                                density="compact"
                                hide-details
                                class="mb-2"
                              />
                              <v-textarea
                                v-model="instanceForm.notes"
                                label="備考"
                                rows="2"
                                density="compact"
                                class="mb-3"
                              />
                              <v-btn
                                type="submit"
                                color="primary"
                                :loading="creatingInstance"
                                :disabled="!instanceForm.item_type_code || !instanceForm.instance_number"
                                block
                              >
                                追加
                              </v-btn>
                            </v-form>
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

    <!-- 項目タイプ詳細ダイアログ -->
    <v-dialog v-model="itemTypeDetailDialog" max-width="700">
      <v-card v-if="selectedItemType">
        <v-card-title>
          {{ selectedItemType.code }}: {{ selectedItemType.name_ja }}
        </v-card-title>
        <v-card-text>
          <div class="mb-3">
            <v-chip :color="categoryColor(selectedItemType.category)" size="small" class="mr-2">
              {{ selectedItemType.category }}
            </v-chip>
            <v-chip :color="selectedItemType.status === 'active' ? 'success' : 'warning'" size="small" class="mr-2">
              {{ selectedItemType.status }}
            </v-chip>
            <v-chip v-if="selectedItemType.pdf_priority" size="small" variant="outlined" class="mr-2">
              優先度: {{ selectedItemType.pdf_priority }}
            </v-chip>
            <v-chip v-if="selectedItemType.investigation_phase" size="small" variant="outlined" class="mr-2">
              {{ selectedItemType.investigation_phase }}
            </v-chip>
          </div>
          <div class="mb-3">
            <strong>英語名:</strong> {{ selectedItemType.name_en }}
          </div>
          <div v-if="selectedItemType.description" class="mb-3">
            <strong>説明:</strong>
            <pre class="bg-grey-lighten-4 pa-3 rounded">{{ selectedItemType.description }}</pre>
          </div>
          <v-row v-if="selectedItemType.frequency || selectedItemType.intensity" class="mb-3">
            <v-col v-if="selectedItemType.frequency" cols="auto">
              <strong>頻度:</strong> {{ selectedItemType.frequency }}
            </v-col>
            <v-col v-if="selectedItemType.intensity" cols="auto">
              <strong>強度:</strong> {{ selectedItemType.intensity }}
            </v-col>
          </v-row>
          <div v-if="selectedItemType.investigation_direction" class="mb-3">
            <strong>調査方向:</strong> {{ selectedItemType.investigation_direction }}
          </div>
          <div class="text-caption text-medium-emphasis">
            カタログバージョン: v{{ selectedItemType.catalog_version }} /
            作成日: {{ formatDate(selectedItemType.created_at) }}
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="primary" @click="itemTypeDetailDialog = false">閉じる</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- インスタンス詳細ダイアログ -->
    <v-dialog v-model="instanceDetailDialog" max-width="700">
      <v-card v-if="selectedInstance">
        <v-card-title>
          患者{{ selectedInstance.patient_id }} / {{ selectedInstance.item_type_code }}-{{ circledNumber(selectedInstance.instance_number) }}
        </v-card-title>
        <v-card-text>
          <div class="mb-3">
            <v-chip
              :color="categoryColor(selectedInstance.item_type_code.split('-')[0])"
              size="small"
              class="mr-2"
            >
              {{ selectedInstance.item_type_code }}
            </v-chip>
            <v-chip v-if="selectedInstance.scene_category" size="small" variant="outlined" class="mr-2">
              {{ selectedInstance.scene_category }}
            </v-chip>
            <v-chip v-if="selectedInstance.date" size="small" variant="outlined" class="mr-2">
              {{ selectedInstance.date }}
            </v-chip>
            <v-icon
              :color="selectedInstance.is_detectable ? 'success' : 'error'"
              size="small"
              class="mr-1"
            >
              {{ selectedInstance.is_detectable ? 'mdi-check-circle' : 'mdi-close-circle' }}
            </v-icon>
            {{ selectedInstance.is_detectable ? '検出可能' : '検出不可能' }}
          </div>
          <div v-if="selectedInstance.description" class="mb-3">
            <strong>説明:</strong>
            <pre class="bg-grey-lighten-4 pa-3 rounded">{{ selectedInstance.description }}</pre>
          </div>
          <div v-if="selectedInstance.investigation_direction_override" class="mb-3">
            <strong>調査方向:</strong> {{ selectedInstance.investigation_direction_override }}
          </div>
          <!-- 3密情報 -->
          <div
            v-if="selectedInstance.density_closed || selectedInstance.density_crowded || selectedInstance.density_close_contact"
            class="mb-3"
          >
            <strong>3密条件:</strong>
            <v-chip v-if="selectedInstance.density_closed" size="x-small" class="mr-1"
              :color="selectedInstance.density_closed === 'High' ? 'error' : 'default'"
            >
              密閉: {{ selectedInstance.density_closed }}
            </v-chip>
            <v-chip v-if="selectedInstance.density_crowded" size="x-small" class="mr-1"
              :color="selectedInstance.density_crowded === 'High' ? 'error' : 'default'"
            >
              密集: {{ selectedInstance.density_crowded }}
            </v-chip>
            <v-chip v-if="selectedInstance.density_close_contact" size="x-small"
              :color="selectedInstance.density_close_contact === 'High' ? 'error' : 'default'"
            >
              密接: {{ selectedInstance.density_close_contact }}
            </v-chip>
          </div>
          <div v-if="selectedInstance.related_patient_ids" class="mb-3">
            <strong>関連患者ID:</strong> {{ selectedInstance.related_patient_ids }}
          </div>
          <div v-if="selectedInstance.notes" class="mb-3">
            <strong>備考:</strong> {{ selectedInstance.notes }}
          </div>
          <div class="text-caption text-medium-emphasis">
            カタログバージョン: v{{ selectedInstance.catalog_version }} /
            作成日: {{ formatDate(selectedInstance.created_at) }}
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="primary" @click="instanceDetailDialog = false">閉じる</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- スナックバー -->
    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="4000">
      {{ snackbar.message }}
    </v-snackbar>
  </v-container>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue';
import { irtApi } from '@/utils/irtApi';
import type { IRTItemType, IRTPatientInstance } from '@/utils/irtApi';

// --- タブ ---
const currentTab = ref('item-types');

// --- 項目タイプ ---
const itemTypes = ref<IRTItemType[]>([]);
const loadingItemTypes = ref(false);
const selectedCategory = ref('');
const itemTypeDetailDialog = ref(false);
const selectedItemType = ref<IRTItemType | null>(null);

const categories = [
  { value: 'D', label: 'D: 疾病臨床' },
  { value: 'T', label: 'T: 追跡可能' },
  { value: 'U', label: 'U: 追跡不可' },
  { value: 'P', label: 'P: 背景リスク' },
  { value: 'E', label: 'E: 環境情報' },
  { value: 'I', label: 'I: 調査プロセス' },
];

const filteredItemTypes = computed(() => {
  if (!selectedCategory.value) return itemTypes.value;
  return itemTypes.value.filter(it => it.category === selectedCategory.value);
});

const itemTypeHeaders = [
  { title: 'コード', key: 'code', width: '90px' },
  { title: 'カテゴリ', key: 'category', width: '90px' },
  { title: '項目名', key: 'name_ja' },
  { title: '優先度', key: 'pdf_priority', width: '80px' },
  { title: 'フェーズ', key: 'investigation_phase', width: '100px' },
  { title: '状態', key: 'status', width: '100px' },
  { title: 'アクション', key: 'actions', width: '80px', sortable: false },
];

// --- 患者インスタンス ---
const selectedPatientId = ref<string | null>(null);
const patientInstances = ref<IRTPatientInstance[]>([]);
const loadingInstances = ref(false);
const instanceDetailDialog = ref(false);
const selectedInstance = ref<IRTPatientInstance | null>(null);
const creatingInstance = ref(false);

const patientIdOptions = computed(() => {
  const ids: string[] = [];
  for (let i = 1; i <= 70; i++) ids.push(String(i));
  for (let i = 101; i <= 108; i++) ids.push(String(i));
  return ids;
});

const itemTypeOptions = computed(() => {
  return itemTypes.value
    .filter(it => it.status === 'active')
    .map(it => ({ title: `${it.code}: ${it.name_ja}`, value: it.code }));
});

const sceneCategories = ['会食', 'イベント', '余暇', '移動', 'その他', '日常'];

const instanceForm = reactive({
  item_type_code: '',
  instance_number: 1,
  date: '',
  description: '',
  scene_category: null as string | null,
  is_detectable: true,
  notes: '',
});

const instanceHeaders = [
  { title: '項目', key: 'item_type_code', width: '110px' },
  { title: '日付', key: 'date', width: '110px' },
  { title: '説明', key: 'description' },
  { title: '場面', key: 'scene_category', width: '80px' },
  { title: '検出', key: 'is_detectable', width: '60px' },
  { title: '', key: 'actions', width: '60px', sortable: false },
];

// --- スナックバー ---
const snackbar = reactive({ show: false, message: '', color: 'success' });

const showSnackbar = (message: string, color = 'success') => {
  snackbar.message = message;
  snackbar.color = color;
  snackbar.show = true;
};

// --- ユーティリティ ---
const formatDate = (dateString: string): string => {
  return new Date(dateString).toLocaleString('ja-JP');
};

const circledNumber = (n: number): string => {
  const circled = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
    '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳'];
  return n >= 1 && n <= 20 ? circled[n - 1] : `(${n})`;
};

const categoryColor = (cat: string): string => {
  const colors: Record<string, string> = {
    D: 'blue', T: 'green', U: 'orange', P: 'purple', E: 'teal', I: 'grey',
  };
  return colors[cat] || 'default';
};

const priorityClass = (priority: string): string => {
  if (priority === '◎') return 'font-weight-bold text-error';
  if (priority === '○') return 'text-warning';
  return 'text-grey';
};

// --- API呼び出し ---
const loadItemTypes = async () => {
  loadingItemTypes.value = true;
  try {
    itemTypes.value = await irtApi.getItemTypes();
  } catch (error) {
    console.error('Failed to load item types:', error);
    showSnackbar('項目タイプの読み込みに失敗しました', 'error');
  } finally {
    loadingItemTypes.value = false;
  }
};

const loadPatientInstances = async () => {
  if (!selectedPatientId.value) return;
  loadingInstances.value = true;
  try {
    patientInstances.value = await irtApi.getPatientInstances(selectedPatientId.value);
  } catch (error) {
    console.error('Failed to load patient instances:', error);
    patientInstances.value = [];
  } finally {
    loadingInstances.value = false;
  }
};

const createInstance = async () => {
  if (!selectedPatientId.value) return;
  creatingInstance.value = true;
  try {
    const latestVersion = itemTypes.value.length > 0
      ? Math.max(...itemTypes.value.map(it => it.catalog_version))
      : 3;

    await irtApi.bulkCreatePatientInstances([{
      catalog_version: latestVersion,
      patient_id: selectedPatientId.value,
      item_type_code: instanceForm.item_type_code,
      instance_number: instanceForm.instance_number,
      date: instanceForm.date || null,
      description: instanceForm.description || null,
      scene_category: instanceForm.scene_category,
      is_detectable: instanceForm.is_detectable,
      notes: instanceForm.notes || null,
    }]);

    // リセット
    instanceForm.item_type_code = '';
    instanceForm.instance_number = 1;
    instanceForm.date = '';
    instanceForm.description = '';
    instanceForm.scene_category = null;
    instanceForm.is_detectable = true;
    instanceForm.notes = '';

    await loadPatientInstances();
    showSnackbar('インスタンスが追加されました');
  } catch (error) {
    console.error('Failed to create instance:', error);
    showSnackbar('インスタンスの追加に失敗しました', 'error');
  } finally {
    creatingInstance.value = false;
  }
};

const showItemTypeDetail = (item: IRTItemType) => {
  selectedItemType.value = item;
  itemTypeDetailDialog.value = true;
};

const showInstanceDetail = (item: IRTPatientInstance) => {
  selectedInstance.value = item;
  instanceDetailDialog.value = true;
};

// --- 初期化 ---
onMounted(() => {
  loadItemTypes();
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
