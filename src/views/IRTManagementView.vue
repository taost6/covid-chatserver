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
              <v-tab value="patient-instances">患者別項目一覧</v-tab>
              <v-tab value="judgments">正誤判定</v-tab>
              <v-tab value="patient-stats">患者別統計</v-tab>
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

                    <div class="d-flex justify-end mb-2">
                      <v-btn color="primary" size="small" @click="showAddItemTypeDialog">
                        項目タイプ追加
                      </v-btn>
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
                          編集
                        </v-btn>
                      </template>
                    </v-data-table>
                  </v-card-text>
                </v-card>
              </v-tabs-window-item>

              <!-- タブ2: 患者別項目一覧 -->
              <v-tabs-window-item value="patient-instances">
                <v-card flat>
                  <v-card-text>
                    <v-row>
                      <!-- 患者選択 + 項目一覧 -->
                      <v-col cols="12" md="8">
                        <v-card>
                          <v-card-title>
                            <v-row align="center" no-gutters>
                              <v-col cols="auto" class="mr-4">患者別項目一覧</v-col>
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

                      <!-- 新規項目追加フォーム -->
                      <v-col cols="12" md="4">
                        <v-card>
                          <v-card-title>項目追加</v-card-title>
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
                                label="項目番号"
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

              <!-- タブ3: 正誤判定 -->
              <v-tabs-window-item value="judgments">
                <v-card flat>
                  <v-card-text>
                    <!-- 上段: バッチ実行パネル -->
                    <v-card class="mb-4" variant="outlined">
                      <v-card-title class="text-subtitle-1">バッチ実行</v-card-title>
                      <v-card-text>
                        <v-row align="center">
                          <v-col cols="12" sm="4">
                            <v-text-field
                              v-model="batchPatientInput"
                              label="患者ID (例: 1-5 or 1,3,5)"
                              density="compact"
                              hide-details
                              :disabled="batchRunning"
                            />
                          </v-col>
                          <v-col cols="6" sm="2">
                            <v-text-field
                              v-model.number="batchRunsPerPatient"
                              label="回数/患者"
                              type="number"
                              min="1"
                              density="compact"
                              hide-details
                              :disabled="batchRunning"
                            />
                          </v-col>
                          <v-col cols="6" sm="2">
                            <v-text-field
                              v-model.number="batchConcurrency"
                              label="並列数"
                              type="number"
                              min="1"
                              max="5"
                              density="compact"
                              hide-details
                              :disabled="batchRunning"
                            />
                          </v-col>
                          <v-col cols="auto">
                            <v-btn
                              v-if="!batchRunning"
                              color="primary"
                              :disabled="!batchPatientInput"
                              @click="startBatch"
                            >
                              バッチ開始
                            </v-btn>
                            <v-btn
                              v-else
                              color="error"
                              @click="stopBatch"
                            >
                              停止
                            </v-btn>
                          </v-col>
                        </v-row>
                        <v-row class="mt-2" dense>
                          <v-col cols="12" sm="4">
                            <fieldset class="batch-fieldset">
                              <legend>患者AI</legend>
                              <v-select
                                v-model="batchPatientModel"
                                :items="modelOptions"
                                label="モデル"
                                density="compact"
                                hide-details
                                :disabled="batchRunning"
                                class="mb-2"
                              />
                              <v-select
                                v-model="batchPatientPromptVersion"
                                :items="patientPromptOptions"
                                label="プロンプト"
                                density="compact"
                                hide-details
                                clearable
                                :disabled="batchRunning"
                              />
                            </fieldset>
                          </v-col>
                          <v-col cols="12" sm="4">
                            <fieldset class="batch-fieldset">
                              <legend>保健師AI</legend>
                              <v-select
                                v-model="batchNurseModel"
                                :items="modelOptions"
                                label="モデル"
                                density="compact"
                                hide-details
                                :disabled="batchRunning"
                                class="mb-2"
                              />
                              <v-select
                                v-model="batchInterviewerPromptVersion"
                                :items="interviewerPromptOptions"
                                label="プロンプト"
                                density="compact"
                                hide-details
                                clearable
                                :disabled="batchRunning"
                              />
                            </fieldset>
                          </v-col>
                          <v-col cols="12" sm="4">
                            <fieldset class="batch-fieldset">
                              <legend>評価者AI</legend>
                              <v-select
                                v-model="batchEvaluatorModel"
                                :items="modelOptions"
                                label="モデル"
                                density="compact"
                                hide-details
                                :disabled="batchRunning"
                                class="mb-2"
                              />
                              <v-select
                                v-model="batchEvaluatorPromptVersion"
                                :items="evaluatorPromptOptions"
                                label="プロンプト"
                                density="compact"
                                hide-details
                                clearable
                                :disabled="batchRunning"
                              />
                            </fieldset>
                          </v-col>
                        </v-row>
                      </v-card-text>
                    </v-card>

                    <!-- 中段: 進捗表示 -->
                    <v-card v-if="batchStatus" class="mb-4" variant="outlined">
                      <v-card-text>
                        <div class="d-flex align-center mb-2">
                          <span class="text-subtitle-2 mr-4">進捗</span>
                          <v-chip size="small" color="info" variant="tonal" class="mr-2">
                            実行中: {{ batchStatus.running }}
                          </v-chip>
                          <v-chip size="small" color="success" variant="tonal" class="mr-2">
                            完了: {{ batchStatus.completed }}
                          </v-chip>
                          <v-chip size="small" color="error" variant="tonal" class="mr-2">
                            失敗: {{ batchStatus.failed }}
                          </v-chip>
                          <v-chip size="small" variant="outlined">
                            合計: {{ batchStatus.total }}
                          </v-chip>
                          <v-spacer />
                          <v-chip
                            size="small"
                            :color="batchStatus.status === 'completed' ? 'success' : batchStatus.status === 'running' ? 'primary' : 'warning'"
                          >
                            {{ batchStatus.status }}
                          </v-chip>
                        </div>
                        <v-progress-linear
                          :model-value="batchStatus.total > 0 ? (batchStatus.completed + batchStatus.failed) / batchStatus.total * 100 : 0"
                          :color="batchStatus.failed > 0 ? 'warning' : 'primary'"
                          height="8"
                          rounded
                        />
                        <div class="text-caption text-right mt-1">
                          {{ batchStatus.completed + batchStatus.failed }} / {{ batchStatus.total }}
                        </div>

                        <!-- バッチ結果テーブル -->
                        <v-data-table
                          v-if="batchStatus.results.length > 0"
                          :headers="batchResultHeaders"
                          :items="batchStatus.results"
                          density="compact"
                          class="mt-3"
                          :items-per-page="10"
                        >
                          <template #item.status="{ item }">
                            <v-chip
                              size="x-small"
                              :color="item.status === 'completed' ? 'success' : item.status === 'failed' ? 'error' : 'primary'"
                            >
                              {{ item.status }}
                            </v-chip>
                          </template>
                          <template #item.score="{ item }">
                            <span v-if="item.correct_count != null">
                              {{ item.correct_count }}/{{ item.total_count }}
                              ({{ item.total_count > 0 ? Math.round(item.correct_count / item.total_count * 100) : 0 }}%)
                            </span>
                            <span v-else class="text-grey">-</span>
                          </template>
                          <template #item.error="{ item }">
                            <span v-if="item.error" class="text-error text-caption">{{ item.error }}</span>
                          </template>
                        </v-data-table>
                      </v-card-text>
                    </v-card>

                    <!-- 下段: 個別セッション判定結果 -->
                    <v-card variant="outlined">
                      <v-card-title class="text-subtitle-1">
                        <v-row align="center" no-gutters>
                          <v-col cols="auto" class="mr-4">セッション判定結果</v-col>
                          <v-col cols="4">
                            <v-select
                              v-model="selectedSessionId"
                              :items="sessionOptions"
                              item-title="label"
                              item-value="value"
                              label="セッション"
                              density="compact"
                              hide-details
                              :loading="loadingSessions"
                              @update:model-value="loadSessionJudgments"
                            />
                          </v-col>
                          <v-col cols="auto" class="ml-4">
                            <v-btn
                              color="primary"
                              size="small"
                              :loading="evaluating"
                              :disabled="!selectedSessionId"
                              @click="evaluateSession"
                            >
                              判定実行
                            </v-btn>
                          </v-col>
                          <v-spacer />
                          <v-col cols="auto">
                            <v-chip v-if="judgments.length > 0" color="primary" size="small">
                              {{ judgments.length }} 件
                            </v-chip>
                          </v-col>
                        </v-row>
                      </v-card-title>
                      <v-card-text>
                        <v-alert
                          v-if="!selectedSessionId"
                          type="info"
                          text="セッションを選択して個別判定結果を確認できます"
                          density="compact"
                          class="mb-4"
                        />

                        <v-alert v-if="evaluating" type="warning" density="compact" class="mb-4">
                          <v-progress-linear indeterminate color="warning" class="mb-2" />
                          LLMにより判定中です...
                        </v-alert>

                        <v-row v-if="judgments.length > 0 && !evaluating" class="mb-4">
                          <v-col cols="auto">
                            <v-chip color="success" variant="tonal" size="small">
                              正答: {{ judgments.filter(j => j.is_correct).length }}
                            </v-chip>
                          </v-col>
                          <v-col cols="auto">
                            <v-chip color="error" variant="tonal" size="small">
                              誤答: {{ judgments.filter(j => !j.is_correct).length }}
                            </v-chip>
                          </v-col>
                          <v-col cols="auto">
                            <v-chip color="info" variant="tonal" size="small">
                              正答率: {{ Math.round(judgments.filter(j => j.is_correct).length / judgments.length * 100) }}%
                            </v-chip>
                          </v-col>
                        </v-row>

                        <v-data-table
                          v-if="selectedSessionId"
                          :headers="judgmentHeaders"
                          :items="judgments"
                          :loading="loadingJudgments"
                          item-value="id"
                          hover
                          density="comfortable"
                        >
                          <template #item.is_correct="{ item }">
                            <v-icon
                              :color="item.is_correct ? 'success' : 'error'"
                              size="small"
                            >
                              {{ item.is_correct ? 'mdi-check-circle' : 'mdi-close-circle' }}
                            </v-icon>
                          </template>
                          <template #item.instance_id="{ item }">
                            <span>{{ instanceLabel(item.instance_id) }}</span>
                          </template>
                          <template #item.confidence="{ item }">
                            <v-chip
                              v-if="item.confidence != null"
                              size="x-small"
                              :color="item.confidence >= 0.8 ? 'success' : item.confidence >= 0.5 ? 'warning' : 'error'"
                              variant="tonal"
                            >
                              {{ (item.confidence * 100).toFixed(0) }}%
                            </v-chip>
                          </template>
                          <template #item.notes="{ item }">
                            <span class="text-body-2">{{ item.notes }}</span>
                          </template>
                        </v-data-table>
                      </v-card-text>
                    </v-card>
                  </v-card-text>
                </v-card>
              </v-tabs-window-item>

              <!-- 患者別統計タブ -->
              <v-tabs-window-item value="patient-stats">
                <v-card flat>
                  <v-card-text>
                    <!-- 患者ID選択 -->
                    <v-row align="center" class="mb-4">
                      <v-col cols="3">
                        <v-select
                          v-model="statsPatientId"
                          :items="patientIdOptions"
                          label="患者ID"
                          density="compact"
                          hide-details
                        />
                      </v-col>
                      <v-col cols="auto">
                        <v-btn
                          color="primary"
                          :loading="loadingStats"
                          :disabled="!statsPatientId"
                          @click="loadPatientStats"
                        >
                          統計表示
                        </v-btn>
                      </v-col>
                    </v-row>

                    <!-- サマリ -->
                    <template v-if="patientStats">
                      <v-row class="mb-4" align="center">
                        <v-col cols="auto">
                          <v-chip color="info" variant="tonal">
                            セッション数: {{ patientStats.total_sessions }}
                          </v-chip>
                        </v-col>
                        <v-col cols="auto" v-for="cat in patientStats.category_stats" :key="cat.category">
                          <v-chip
                            :color="cat.avg_accuracy >= 0.7 ? 'success' : cat.avg_accuracy >= 0.4 ? 'warning' : 'error'"
                            variant="tonal"
                          >
                            {{ cat.category }}: {{ (cat.avg_accuracy * 100).toFixed(0) }}%
                            <span class="text-caption ml-1">({{ cat.total_instances }}項目)</span>
                          </v-chip>
                        </v-col>
                      </v-row>

                      <!-- 項目別正答率テーブル -->
                      <v-card variant="outlined" class="mb-4">
                        <v-card-title class="text-subtitle-1">項目別正答率</v-card-title>
                        <v-data-table
                          :headers="patientItemHeaders"
                          :items="patientStats.item_stats.filter(i => i.is_detectable)"
                          item-value="instance_id"
                          hover
                          density="comfortable"
                          show-expand
                        >
                          <template #item.item_type_code="{ item }">
                            <v-chip size="small" variant="tonal" :color="item.is_detectable ? 'primary' : 'grey'">
                              {{ item.item_type_code }}-{{ item.instance_number }}
                            </v-chip>
                          </template>
                          <template #item.accuracy="{ item }">
                            <div class="d-flex align-center" style="min-width:120px">
                              <v-progress-linear
                                :model-value="item.accuracy * 100"
                                :color="item.accuracy >= 0.7 ? 'success' : item.accuracy >= 0.4 ? 'warning' : 'error'"
                                height="18"
                                rounded
                                class="mr-2"
                                style="flex:1"
                              >
                                <template #default>
                                  <span class="text-caption">{{ (item.accuracy * 100).toFixed(0) }}%</span>
                                </template>
                              </v-progress-linear>
                            </div>
                          </template>
                          <template #expanded-row="{ columns, item }">
                            <tr>
                              <td :colspan="columns.length" class="pa-2">
                                <v-table density="compact" class="ml-8">
                                  <thead>
                                    <tr>
                                      <th>セッションID</th>
                                      <th>結果</th>
                                      <th>確信度</th>
                                      <th>メモ</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    <tr v-for="(sj, idx) in item.sessions" :key="idx">
                                      <td class="text-caption">{{ sj.session_id.substring(0, 12) }}...</td>
                                      <td>
                                        <v-icon :color="sj.is_correct ? 'success' : 'error'" size="small">
                                          {{ sj.is_correct ? 'mdi-check-circle' : 'mdi-close-circle' }}
                                        </v-icon>
                                      </td>
                                      <td>{{ sj.confidence != null ? (sj.confidence * 100).toFixed(0) + '%' : '-' }}</td>
                                      <td class="text-caption">{{ sj.notes || '-' }}</td>
                                    </tr>
                                  </tbody>
                                </v-table>
                              </td>
                            </tr>
                          </template>
                        </v-data-table>
                      </v-card>

                      <!-- セッション比較テーブル -->
                      <v-card variant="outlined">
                        <v-card-title class="text-subtitle-1">セッション比較</v-card-title>
                        <v-data-table
                          :headers="sessionCompareHeaders"
                          :items="patientStats.sessions"
                          density="compact"
                          hover
                        >
                          <template #item.created_at="{ item }">
                            {{ item.created_at ? new Date(item.created_at).toLocaleString('ja-JP') : '-' }}
                          </template>
                          <template #item.accuracy="{ item }">
                            <div class="d-flex align-center" style="min-width:140px">
                              <span class="mr-2">{{ item.correct_count }}/{{ item.total_count }}</span>
                              <v-progress-linear
                                :model-value="item.accuracy * 100"
                                :color="item.accuracy >= 0.7 ? 'success' : item.accuracy >= 0.4 ? 'warning' : 'error'"
                                height="16"
                                rounded
                                style="flex:1"
                              >
                                <template #default>
                                  <span class="text-caption">{{ (item.accuracy * 100).toFixed(0) }}%</span>
                                </template>
                              </v-progress-linear>
                            </div>
                          </template>
                        </v-data-table>
                      </v-card>
                    </template>

                    <!-- データなし -->
                    <v-alert
                      v-else-if="statsPatientId && !loadingStats && statsLoadedOnce"
                      type="info"
                      variant="tonal"
                      class="mt-4"
                    >
                      この患者の判定データはありません。
                    </v-alert>
                  </v-card-text>
                </v-card>
              </v-tabs-window-item>
            </v-tabs-window>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 項目タイプ編集ダイアログ -->
    <v-dialog v-model="itemTypeDetailDialog" max-width="700">
      <v-card v-if="editingItemType">
        <v-card-title>
          {{ editingItemType.code }} を編集
        </v-card-title>
        <v-card-text>
          <v-text-field v-model="editingItemType.name_ja" label="項目名" density="compact" class="mb-2" />
          <v-textarea v-model="editingItemType.description" label="説明" rows="4" density="compact" class="mb-2" />
          <v-row>
            <v-col cols="4">
              <v-select v-model="editingItemType.investigation_direction" :items="['forward','backward','both','none']" label="調査方向" density="compact" clearable />
            </v-col>
            <v-col cols="4">
              <v-select v-model="editingItemType.frequency" :items="['High','Low','Variable']" label="頻度" density="compact" clearable />
            </v-col>
            <v-col cols="4">
              <v-select v-model="editingItemType.intensity" :items="['High','Low','Variable']" label="強度" density="compact" clearable />
            </v-col>
          </v-row>
          <v-select v-model="editingItemType.status" :items="['active','candidate','deprecated']" label="状態" density="compact" class="mt-2" />
        </v-card-text>
        <v-card-actions>
          <v-btn color="error" variant="text" @click="deleteItemType" :loading="savingItemType">削除</v-btn>
          <v-spacer />
          <v-btn variant="text" @click="itemTypeDetailDialog = false">キャンセル</v-btn>
          <v-btn color="primary" @click="saveItemType" :loading="savingItemType">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 項目タイプ追加ダイアログ -->
    <v-dialog v-model="addItemTypeDialog" max-width="700">
      <v-card>
        <v-card-title>項目タイプ追加</v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="4">
              <v-text-field v-model="newItemType.code" label="コード (例: T-3)" density="compact" required />
            </v-col>
            <v-col cols="4">
              <v-select v-model="newItemType.category" :items="categories.map(c => c.value)" label="カテゴリ" density="compact" required />
            </v-col>
            <v-col cols="4">
              <v-select v-model="newItemType.status" :items="['active','candidate','deprecated']" label="状態" density="compact" />
            </v-col>
          </v-row>
          <v-text-field v-model="newItemType.name_ja" label="項目名（日本語）" density="compact" class="mb-2" required />
          <v-text-field v-model="newItemType.name_en" label="項目名（英語）" density="compact" class="mb-2" required />
          <v-textarea v-model="newItemType.description" label="説明" rows="3" density="compact" class="mb-2" />
          <v-row>
            <v-col cols="4">
              <v-select v-model="newItemType.investigation_direction" :items="['forward','backward','both','none']" label="調査方向" density="compact" clearable />
            </v-col>
            <v-col cols="4">
              <v-select v-model="newItemType.frequency" :items="['High','Low','Variable']" label="頻度" density="compact" clearable />
            </v-col>
            <v-col cols="4">
              <v-select v-model="newItemType.intensity" :items="['High','Low','Variable']" label="強度" density="compact" clearable />
            </v-col>
          </v-row>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="addItemTypeDialog = false">キャンセル</v-btn>
          <v-btn
            color="primary"
            @click="createItemType"
            :loading="creatingItemType"
            :disabled="!newItemType.code || !newItemType.category || !newItemType.name_ja || !newItemType.name_en"
          >
            追加
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 項目編集ダイアログ -->
    <v-dialog v-model="instanceDetailDialog" max-width="700">
      <v-card v-if="editingInstance">
        <v-card-title>
          患者{{ editingInstance.patient_id }} / {{ editingInstance.item_type_code }}-{{ circledNumber(editingInstance.instance_number) }} を編集
        </v-card-title>
        <v-card-text>
          <v-row>
            <v-col cols="6">
              <v-select v-model="editingInstance.item_type_code" :items="itemTypeOptions" label="項目タイプ" density="compact" />
            </v-col>
            <v-col cols="3">
              <v-text-field v-model.number="editingInstance.instance_number" label="番号" type="number" min="1" density="compact" />
            </v-col>
            <v-col cols="3">
              <v-text-field v-model="editingInstance.date" label="日付" density="compact" />
            </v-col>
          </v-row>
          <v-textarea v-model="editingInstance.description" label="説明" rows="3" density="compact" class="mb-2" />
          <v-row>
            <v-col cols="6">
              <v-select v-model="editingInstance.scene_category" :items="sceneCategories" label="場面カテゴリ" density="compact" clearable />
            </v-col>
            <v-col cols="6">
              <v-select v-model="editingInstance.investigation_direction_override" :items="['forward','backward','both']" label="調査方向" density="compact" clearable />
            </v-col>
          </v-row>
          <v-row>
            <v-col cols="4">
              <v-select v-model="editingInstance.density_closed" :items="['High','Low','Unknown']" label="密閉" density="compact" clearable />
            </v-col>
            <v-col cols="4">
              <v-select v-model="editingInstance.density_crowded" :items="['High','Low','Unknown']" label="密集" density="compact" clearable />
            </v-col>
            <v-col cols="4">
              <v-select v-model="editingInstance.density_close_contact" :items="['High','Low','Unknown']" label="密接" density="compact" clearable />
            </v-col>
          </v-row>
          <v-text-field v-model="editingInstance.related_patient_ids" label="関連患者ID (JSON配列)" density="compact" class="mb-2" />
          <v-checkbox v-model="editingInstance.is_detectable" label="検出可能" density="compact" hide-details class="mb-2" />
          <v-textarea v-model="editingInstance.notes" label="備考" rows="2" density="compact" />
        </v-card-text>
        <v-card-actions>
          <v-btn color="error" variant="text" @click="deleteInstance" :loading="savingInstance">削除</v-btn>
          <v-spacer />
          <v-btn variant="text" @click="instanceDetailDialog = false">キャンセル</v-btn>
          <v-btn color="primary" @click="saveInstance" :loading="savingInstance">保存</v-btn>
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
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue';
import { irtApi } from '@/utils/irtApi';
import type { IRTItemType, IRTPatientInstance, IRTResponseJudgment, BatchStatus, PatientStatsResponse } from '@/utils/irtApi';

// --- タブ ---
const currentTab = ref('item-types');

// --- 項目タイプ ---
const itemTypes = ref<IRTItemType[]>([]);
const loadingItemTypes = ref(false);
const selectedCategory = ref('');
const itemTypeDetailDialog = ref(false);
const addItemTypeDialog = ref(false);
const creatingItemType = ref(false);
const newItemType = ref({
  code: '',
  category: '',
  name_ja: '',
  name_en: '',
  description: '',
  investigation_direction: null as string | null,
  frequency: null as string | null,
  intensity: null as string | null,
  status: 'active',
});

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
  { title: '状態', key: 'status', width: '100px' },
  { title: '', key: 'actions', width: '80px', sortable: false },
];

// --- 患者別項目一覧 ---
const selectedPatientId = ref<string | null>(null);
const patientInstances = ref<IRTPatientInstance[]>([]);
const loadingInstances = ref(false);
const instanceDetailDialog = ref(false);
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
    showSnackbar('項目が追加されました');
  } catch (error) {
    console.error('Failed to create instance:', error);
    showSnackbar('項目の追加に失敗しました', 'error');
  } finally {
    creatingInstance.value = false;
  }
};

// --- 編集機能 ---
const editingItemType = ref<Record<string, unknown> | null>(null);
const savingItemType = ref(false);
const editingInstance = ref<Record<string, unknown> | null>(null);
const savingInstance = ref(false);

const showAddItemTypeDialog = () => {
  const latestVersion = itemTypes.value.length > 0
    ? Math.max(...itemTypes.value.map(it => it.catalog_version))
    : 1;
  newItemType.value = {
    code: '', category: '', name_ja: '', name_en: '', description: '',
    investigation_direction: null, frequency: null, intensity: null, status: 'active',
  };
  Object.assign(newItemType.value, { catalog_version: latestVersion });
  addItemTypeDialog.value = true;
};

const createItemType = async () => {
  creatingItemType.value = true;
  try {
    await irtApi.createItemType(newItemType.value);
    await loadItemTypes();
    addItemTypeDialog.value = false;
    showSnackbar('項目タイプを追加しました');
  } catch (error) {
    console.error('Failed to create item type:', error);
    showSnackbar('項目タイプの追加に失敗しました', 'error');
  } finally {
    creatingItemType.value = false;
  }
};

const showItemTypeDetail = (item: IRTItemType) => {
  editingItemType.value = { ...item };
  itemTypeDetailDialog.value = true;
};

const saveItemType = async () => {
  if (!editingItemType.value) return;
  savingItemType.value = true;
  try {
    const id = editingItemType.value.id as number;
    const { id: _, created_at: __, ...data } = editingItemType.value;
    await irtApi.updateItemType(id, data);
    await loadItemTypes();
    itemTypeDetailDialog.value = false;
    showSnackbar('項目タイプを更新しました');
  } catch (error) {
    console.error('Failed to update item type:', error);
    showSnackbar('更新に失敗しました', 'error');
  } finally {
    savingItemType.value = false;
  }
};

const deleteItemType = async () => {
  if (!editingItemType.value || !confirm('この項目タイプを削除してもよろしいですか？')) return;
  savingItemType.value = true;
  try {
    await irtApi.deleteItemType(editingItemType.value.id as number);
    await loadItemTypes();
    itemTypeDetailDialog.value = false;
    showSnackbar('項目タイプを削除しました');
  } catch (error) {
    console.error('Failed to delete item type:', error);
    showSnackbar('削除に失敗しました', 'error');
  } finally {
    savingItemType.value = false;
  }
};

const showInstanceDetail = (item: IRTPatientInstance) => {
  editingInstance.value = { ...item };
  instanceDetailDialog.value = true;
};

const saveInstance = async () => {
  if (!editingInstance.value) return;
  savingInstance.value = true;
  try {
    const id = editingInstance.value.id as number;
    const { id: _, created_at: __, ...data } = editingInstance.value;
    await irtApi.updatePatientInstance(id, data);
    await loadPatientInstances();
    instanceDetailDialog.value = false;
    showSnackbar('項目を更新しました');
  } catch (error) {
    console.error('Failed to update instance:', error);
    showSnackbar('更新に失敗しました', 'error');
  } finally {
    savingInstance.value = false;
  }
};

const deleteInstance = async () => {
  if (!editingInstance.value || !confirm('この項目を削除してもよろしいですか？')) return;
  savingInstance.value = true;
  try {
    await irtApi.deletePatientInstance(editingInstance.value.id as number);
    await loadPatientInstances();
    instanceDetailDialog.value = false;
    showSnackbar('項目を削除しました');
  } catch (error) {
    console.error('Failed to delete instance:', error);
    showSnackbar('削除に失敗しました', 'error');
  } finally {
    savingInstance.value = false;
  }
};

// --- バッチ実行 ---
const batchPatientInput = ref('');
const batchRunsPerPatient = ref(1);
const batchConcurrency = ref(2);
const batchNurseModel = ref('gpt-4.1');
const batchPatientModel = ref('gpt-4.1');
const batchEvaluatorModel = ref('gpt-4.1');
const modelOptions = ['gpt-4.1', 'gpt-5-mini', 'gpt-5.2', 'gpt-5.4', 'gpt-5-nano'];
const batchPatientPromptVersion = ref<number | null>(null);
const batchInterviewerPromptVersion = ref<number | null>(null);
const batchEvaluatorPromptVersion = ref<number | null>(null);
const patientPromptOptions = ref<Array<{ title: string; value: number }>>([]);
const interviewerPromptOptions = ref<Array<{ title: string; value: number }>>([]);
const evaluatorPromptOptions = ref<Array<{ title: string; value: number }>>([]);
const batchStatus = ref<BatchStatus | null>(null);
const batchRunning = computed(() =>
  batchStatus.value?.status === 'running' || batchStatus.value?.status === 'stopping'
);
let batchPollTimer: ReturnType<typeof setInterval> | null = null;

const batchResultHeaders = [
  { title: '患者ID', key: 'patient_id', width: '80px' },
  { title: 'Run', key: 'run_number', width: '60px' },
  { title: '状態', key: 'status', width: '90px' },
  { title: 'スコア', key: 'score', width: '120px' },
  { title: 'セッションID', key: 'session_id', width: '200px' },
  { title: 'エラー', key: 'error' },
];

const parsePatientIds = (input: string): string[] => {
  const ids: string[] = [];
  for (const part of input.split(',')) {
    const trimmed = part.trim();
    if (trimmed.includes('-')) {
      const [start, end] = trimmed.split('-').map(Number);
      if (!isNaN(start) && !isNaN(end)) {
        for (let i = start; i <= end; i++) ids.push(String(i));
      }
    } else if (trimmed) {
      ids.push(trimmed);
    }
  }
  return ids;
};

const startBatch = async () => {
  const patientIds = parsePatientIds(batchPatientInput.value);
  if (patientIds.length === 0) {
    showSnackbar('患者IDを入力してください', 'error');
    return;
  }
  try {
    const result = await irtApi.startBatch(
      patientIds, batchRunsPerPatient.value, batchConcurrency.value,
      batchNurseModel.value, batchPatientModel.value, batchEvaluatorModel.value,
      batchPatientPromptVersion.value, batchInterviewerPromptVersion.value,
      batchEvaluatorPromptVersion.value
    );
    batchStatus.value = {
      batch_id: result.batch_id,
      status: 'running',
      total: result.total_tasks,
      completed: 0,
      failed: 0,
      running: 0,
      results: [],
    };
    showSnackbar(`バッチ開始: ${result.total_tasks} タスク`);
    startBatchPolling(result.batch_id);
  } catch (error) {
    console.error('Failed to start batch:', error);
    showSnackbar('バッチ開始に失敗しました', 'error');
  }
};

const stopBatch = async () => {
  if (!batchStatus.value) return;
  try {
    await irtApi.stopBatch(batchStatus.value.batch_id);
    showSnackbar('バッチ停止をリクエストしました');
  } catch (error) {
    console.error('Failed to stop batch:', error);
    showSnackbar('バッチ停止に失敗しました', 'error');
  }
};

const startBatchPolling = (batchId: string) => {
  stopBatchPolling();
  batchPollTimer = setInterval(async () => {
    try {
      const status = await irtApi.getBatchStatus(batchId);
      batchStatus.value = status;
      if (status.status === 'completed' || status.status === 'stopped') {
        stopBatchPolling();
        // バッチ完了後にセッション一覧を更新
        await loadSessions();
      }
    } catch (error) {
      console.error('Failed to poll batch status:', error);
    }
  }, 2000);
};

const stopBatchPolling = () => {
  if (batchPollTimer) {
    clearInterval(batchPollTimer);
    batchPollTimer = null;
  }
};

// --- 正誤判定 ---
const selectedSessionId = ref<string | null>(null);
const sessions = ref<Array<{ session_id: string; user_name: string; user_role: string; patient_id: string | null; started_at: string }>>([]);
const judgments = ref<IRTResponseJudgment[]>([]);
const loadingSessions = ref(false);
const loadingJudgments = ref(false);
const evaluating = ref(false);
// 項目ID→ラベルのマップ（判定結果表示用）
const instanceMap = ref<Record<number, string>>({});

const sessionOptions = computed(() => {
  return sessions.value
    .filter(s => s.patient_id)
    .map(s => ({
      value: s.session_id,
      label: `${s.patient_id ? '患者' + s.patient_id : ''} / ${s.user_role} / ${s.user_name} (${new Date(s.started_at).toLocaleDateString('ja-JP')})`,
    }));
});

const judgmentHeaders = [
  { title: 'IRT項目', key: 'instance_id', width: '200px' },
  { title: '正誤', key: 'is_correct', width: '70px' },
  { title: '確信度', key: 'confidence', width: '90px' },
  { title: '根拠', key: 'notes' },
];

const instanceLabel = (instanceId: number): string => {
  return instanceMap.value[instanceId] || `#${instanceId}`;
};

const loadSessions = async () => {
  loadingSessions.value = true;
  try {
    sessions.value = await irtApi.getSessions();
  } catch (error) {
    console.error('Failed to load sessions:', error);
  } finally {
    loadingSessions.value = false;
  }
};

const loadSessionJudgments = async () => {
  if (!selectedSessionId.value) return;
  loadingJudgments.value = true;
  try {
    judgments.value = await irtApi.getSessionJudgments(selectedSessionId.value);
    // 選択されたセッションの患者IDから項目マップを構築
    const session = sessions.value.find(s => s.session_id === selectedSessionId.value);
    if (session?.patient_id) {
      await buildInstanceMap(session.patient_id);
    }
  } catch (error) {
    console.error('Failed to load judgments:', error);
    judgments.value = [];
  } finally {
    loadingJudgments.value = false;
  }
};

const buildInstanceMap = async (patientId: string) => {
  try {
    const instances = await irtApi.getPatientInstances(patientId);
    const map: Record<number, string> = {};
    for (const inst of instances) {
      const typeName = itemTypes.value.find(it => it.code === inst.item_type_code)?.name_ja || inst.item_type_code;
      map[inst.id] = `${inst.item_type_code}-${circledNumber(inst.instance_number)} ${typeName}`;
    }
    instanceMap.value = map;
  } catch (error) {
    console.error('Failed to build instance map:', error);
  }
};

const evaluateSession = async () => {
  if (!selectedSessionId.value) return;
  evaluating.value = true;
  try {
    const result = await irtApi.evaluateSession(selectedSessionId.value);
    judgments.value = result.judgments;
    // 項目マップも更新
    const session = sessions.value.find(s => s.session_id === selectedSessionId.value);
    if (session?.patient_id) {
      await buildInstanceMap(session.patient_id);
    }
    showSnackbar(`${result.judged_count} 件の判定が完了しました`);
  } catch (error) {
    console.error('Failed to evaluate session:', error);
    showSnackbar('判定に失敗しました', 'error');
  } finally {
    evaluating.value = false;
  }
};

// 判定タブに切り替えた時にセッション一覧をロード
const loadPromptOptions = async () => {
  try {
    const allPrompts = await irtApi.getPrompts();
    patientPromptOptions.value = allPrompts
      .filter(p => p.template_type === 'patient')
      .sort((a, b) => b.version - a.version)
      .map(p => ({
        title: `v${p.version}${p.is_active ? ' (active)' : ''}${p.description ? ' - ' + p.description : ''}`,
        value: p.version,
      }));
    interviewerPromptOptions.value = allPrompts
      .filter(p => p.template_type === 'interviewer')
      .sort((a, b) => b.version - a.version)
      .map(p => ({
        title: `v${p.version}${p.is_active ? ' (active)' : ''}${p.description ? ' - ' + p.description : ''}`,
        value: p.version,
      }));
    evaluatorPromptOptions.value = allPrompts
      .filter(p => p.template_type === 'evaluator')
      .sort((a, b) => b.version - a.version)
      .map(p => ({
        title: `v${p.version}${p.is_active ? ' (active)' : ''}${p.description ? ' - ' + p.description : ''}`,
        value: p.version,
      }));
  } catch (error) {
    console.error('Failed to load prompt options:', error);
  }
};

watch(currentTab, (tab) => {
  if (tab === 'judgments') {
    if (sessions.value.length === 0) loadSessions();
    if (patientPromptOptions.value.length === 0) loadPromptOptions();
  }
});

// --- 患者別統計 ---
const statsPatientId = ref<string | null>(null);
const patientStats = ref<PatientStatsResponse | null>(null);
const loadingStats = ref(false);
const statsLoadedOnce = ref(false);

const patientItemHeaders = [
  { title: '項目', key: 'item_type_code', width: '110px' },
  { title: '説明', key: 'description' },
  { title: '判定数', key: 'total_judgments', width: '80px' },
  { title: '正答数', key: 'correct_count', width: '80px' },
  { title: '正答率', key: 'accuracy', width: '140px' },
  { title: '', key: 'data-table-expand' },
];

const sessionCompareHeaders = [
  { title: 'セッションID', key: 'session_id', width: '200px' },
  { title: '日時', key: 'created_at', width: '180px' },
  { title: '保健師モデル', key: 'nurse_model', width: '130px' },
  { title: '患者モデル', key: 'patient_model', width: '130px' },
  { title: '正答率', key: 'accuracy', width: '180px' },
];

const loadPatientStats = async () => {
  if (!statsPatientId.value) return;
  loadingStats.value = true;
  statsLoadedOnce.value = false;
  try {
    patientStats.value = await irtApi.getPatientStats(statsPatientId.value);
    statsLoadedOnce.value = true;
    if (patientStats.value.total_sessions === 0) {
      patientStats.value = null;
    }
  } catch (error) {
    console.error('Failed to load patient stats:', error);
    showSnackbar('患者統計の読み込みに失敗しました', 'error');
    patientStats.value = null;
    statsLoadedOnce.value = true;
  } finally {
    loadingStats.value = false;
  }
};

// --- 初期化 ---
onMounted(() => {
  loadItemTypes();
});

onUnmounted(() => {
  stopBatchPolling();
});
</script>

<style scoped>
pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 0.85em;
  line-height: 1.4;
}
.batch-fieldset {
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity, 0.12));
  border-radius: 4px;
  padding: 8px 12px 12px;
}
.batch-fieldset legend {
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0 4px;
  color: rgba(var(--v-theme-on-surface), 0.6);
}
</style>
