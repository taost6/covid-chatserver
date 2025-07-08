<template>
  <v-app style="height: 100vh; display: flex; flex-direction: column;">
    <v-main style="flex: 1 1 auto; overflow: auto;">
      <v-container fluid class="pa-md-6 pa-4">
        <!-- Header -->
        <AppHeader 
          :custom-status="'調査評価レポート'"
          @toggle-drawer="drawer = !drawer" 
        />
        

        <!-- Loading State -->
        <div v-if="loading" class="text-center py-12">
          <v-progress-circular 
            indeterminate 
            size="64" 
            color="primary"
            class="mb-4"
          ></v-progress-circular>
          <h3 class="text-h6">評価レポートを読み込み中...</h3>
        </div>

        <!-- Error State -->
        <v-alert 
          v-else-if="error" 
          type="error" 
          variant="tonal"
          class="mb-6"
        >
          <v-alert-title>エラー</v-alert-title>
          {{ error }}
        </v-alert>

        <!-- Debriefing Content -->
        <div v-else-if="debriefingData" class="debriefing-content">
          <!-- Overall Score Card -->
          <v-card class="mb-6" elevation="2">
            <v-card-title class="text-h5 font-weight-bold d-flex align-center bg-primary text-white">
              <v-icon class="mr-3" size="large">mdi-star-circle</v-icon>
              総合評価
            </v-card-title>
            <v-card-text class="pa-6">
              <div class="text-center">
                <div class="text-h2 font-weight-bold text-primary mb-2">
                  {{ debriefingData.overall_score }}
                  <span class="text-h4 text-medium-emphasis">/ 100</span>
                </div>
                <v-progress-linear 
                  :model-value="debriefingData.overall_score" 
                  color="primary" 
                  height="12" 
                  rounded
                  class="mx-auto"
                  style="max-width: 300px;"
                ></v-progress-linear>
              </div>
            </v-card-text>
          </v-card>

          <!-- Patient Info Panel -->
          <PatientInfoPanel :show-staff-info="true" />

          <!-- Evaluation Details -->
          <v-card class="mb-6 mt-6" elevation="2">
            <v-card-title class="text-h5 font-weight-bold bg-surface-variant">
              講評
            </v-card-title>
            <v-card-text class="pa-6">
              <v-row>
                <v-col cols="12" md="6">
                  <div class="mb-6">
                    <h4 class="text-h6 font-weight-bold mb-3 d-flex align-center">
                      <v-icon color="blue" class="mr-2">mdi-information-outline</v-icon>
                      1. 感染に関わる情報の聴取割合
                    </h4>
                    <p :class="[fontSizeClass, 'pl-8']">{{ debriefingData.information_retrieval_ratio }}</p>
                  </div>
                </v-col>
                <v-col cols="12" md="6">
                  <div class="mb-6">
                    <h4 class="text-h6 font-weight-bold mb-3 d-flex align-center">
                      <v-icon color="green" class="mr-2">mdi-quality-high</v-icon>
                      2. 回答した情報の質
                    </h4>
                    <p :class="[fontSizeClass, 'pl-8']">{{ debriefingData.information_quality }}</p>
                  </div>
                </v-col>
              </v-row>
              
              <v-divider class="my-6"></v-divider>
              
              <div>
                <h4 class="text-h6 font-weight-bold mb-3 d-flex align-center">
                  <v-icon color="orange" class="mr-2">mdi-comment-text-outline</v-icon>
                  3. 総評
                </h4>
                <p :class="[fontSizeClass, 'pl-8']">{{ debriefingData.overall_comment }}</p>
              </div>
            </v-card-text>
          </v-card>

          <!-- Micro Evaluations -->
          <v-card elevation="2">
            <v-card-title class="text-h5 font-weight-bold bg-surface-variant">
              <v-icon class="mr-3">mdi-comment-quote-outline</v-icon>
              個別の発言へのフィードバック
            </v-card-title>
            <v-card-text class="pa-6">
              <div v-if="debriefingData.micro_evaluations && debriefingData.micro_evaluations.length > 0">
                <v-timeline side="end" density="compact">
                  <v-timeline-item
                    v-for="(item, i) in debriefingData.micro_evaluations"
                    :key="i"
                    :dot-color="getEvaluationColor(item.evaluation_symbol)"
                    size="large"
                  >
                    <template v-slot:icon>
                      <span class="text-white font-weight-bold">
                        {{ item.evaluation_symbol }}
                      </span>
                    </template>
                    
                    <v-card 
                      class="mb-4" 
                      elevation="1"
                      :style="{ borderLeft: `4px solid ${getEvaluationColorHex(item.evaluation_symbol)}` }"
                    >
                      <v-card-text>
                        <blockquote :class="[fontSizeClass, 'font-italic mb-3 pa-3 bg-surface-variant rounded']" style="border-left: none;">
                          "{{ item.utterance }}"
                        </blockquote>
                        <p :class="[fontSizeClass, 'mb-0']">{{ item.advice }}</p>
                      </v-card-text>
                    </v-card>
                  </v-timeline-item>
                </v-timeline>
              </div>
              <div v-else class="text-center py-6 text-medium-emphasis">
                個別の発言評価はありません
              </div>
            </v-card-text>
          </v-card>
        </div>

        <!-- Empty State -->
        <div v-else class="text-center py-12">
          <v-icon size="64" color="medium-emphasis" class="mb-4">mdi-file-document-outline</v-icon>
          <h3 class="text-h6 text-medium-emphasis">評価レポートが見つかりません</h3>
        </div>
      </v-container>
    </v-main>

    <!-- Action Bar -->
    <v-footer app class="bg-surface pa-4 no-print">
      <v-container fluid>
        <div class="d-flex justify-center">
          <v-btn 
            color="primary" 
            size="large" 
            variant="elevated"
            @click="startNewSession"
            class="px-8"
          >
            <v-icon start>mdi-refresh</v-icon>
            新しいセッションを開始する
          </v-btn>
        </div>
      </v-container>
    </v-footer>

    <!-- Navigation Drawer -->
    <DebriefingDrawer v-model="drawer" />
  </v-app>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useSessionStore } from '@/stores/sessionStore';
import { useChatStore } from '@/stores/chatStore';
import { usePatientStore } from '@/stores/patientStore';
import AppHeader from '@/components/layout/AppHeader.vue';
import DebriefingDrawer from '@/components/layout/DebriefingDrawer.vue';
import PatientInfoPanel from '@/components/features/PatientInfoPanel.vue';
import type { DebriefingData, PatientInfo } from '@/types';

const route = useRoute();
const router = useRouter();

// Stores
const sessionStore = useSessionStore();
const chatStore = useChatStore();
const patientStore = usePatientStore();

const loading = ref(true);
const error = ref<string | null>(null);
const debriefingData = ref<DebriefingData | null>(null);
const drawer = ref(false);
const fontSize = ref(1);

// Computed class for font size
const fontSizeClass = computed(() => {
  switch (fontSize.value) {
    case 0: return 'text-caption';
    case 1: return 'text-body-1';
    case 2: return 'text-h6';
    default: return 'text-body-1';
  }
});

// Get evaluation color based on symbol
const getEvaluationColor = (symbol: string) => {
  switch (symbol) {
    case '◎': return 'teal';
    case '○': return 'indigo';
    case '△': return 'orange';
    case '✕': return 'red';
    default: return 'grey-lighten-1';
  }
};


// Get evaluation color hex based on symbol
const getEvaluationColorHex = (symbol: string) => {
  switch (symbol) {
    case '◎': return '#26A69A';
    case '○': return '#5C6BC0';
    case '△': return '#FF9800';
    case '✕': return '#F44336';
    default: return '#BDBDBD';
  }
};

// Load debriefing data from route params or API
const loadDebriefingData = async () => {
  try {
    loading.value = true;
    error.value = null;
    
    // Check if data is passed via route state
    if (route.params.data) {
      debriefingData.value = JSON.parse(route.params.data as string);
      loading.value = false;
      return;
    }
    
    // Check if session ID is provided to fetch from API
    const sessionId = route.params.sessionId as string;
    if (sessionId) {
      // Fetch debriefing data from API
      const protocol = window.location.protocol;
      const host = window.location.host;
      const url = `${protocol}//${host}/v1/session/${sessionId}/debriefing`;
      
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      debriefingData.value = data;
      
      // Also try to load session data for patient info
      await loadSessionDataFromApi(sessionId);
    } else {
      throw new Error('セッションIDまたは評価データが指定されていません');
    }
  } catch (err) {
    console.error('Failed to load debriefing data:', err);
    error.value = err instanceof Error ? err.message : '評価レポートの読み込みに失敗しました';
  } finally {
    loading.value = false;
  }
};

// Load session data from API using session ID
const loadSessionDataFromApi = async (sessionId: string) => {
  try {
    console.log('[DebriefingView] Loading session data for session ID:', sessionId);
    const protocol = window.location.protocol.replace(':', '');
    const host = window.location.host;
    const url = `${protocol}://${host}/v1/session/${sessionId}`;
    
    const response = await fetch(url);
    if (response.ok) {
      const sessionData = await response.json();
      console.log('[DebriefingView] Session data loaded from API:', sessionData);
      
      // Create mock user for evaluation page display
      const user = {
        userId: sessionData.user_id || 'unknown',
        sessionId: sessionData.session_id || sessionId,
        userName: sessionData.user_name || 'Unknown User',
        role: sessionData.user_role || '保健師',
        status: 'Established' as const,
        targetPatientId: sessionData.patient_id || null,
      };
      
      console.log('[DebriefingView] Setting user for evaluation page:', user);
      sessionStore.setUser(user);
      sessionStore.setSessionId(sessionData.session_id || sessionId);
      // Don't set connection status to avoid interfering with active sessions
      
      if (sessionData.interview_date) {
        sessionStore.setInterviewDate(sessionData.interview_date);
      }
      
      // Set patient info
      if (sessionData.patient_info) {
        console.log('[DebriefingView] Setting patient info from API:', sessionData.patient_info);
        patientStore.setPatientInfo(sessionData.patient_info);
        patientStore.setSelectedPatientId(sessionData.patient_id);
      } else if (sessionData.patient_id) {
        console.log('[DebriefingView] Setting patient ID from API:', sessionData.patient_id);
        patientStore.setSelectedPatientId(sessionData.patient_id);
      }
    } else {
      console.error('[DebriefingView] Failed to load session data from API:', response.status);
    }
  } catch (error) {
    console.error('[DebriefingView] Error loading session data from API:', error);
  }
};



const startNewSession = () => {
  // Clear all session data
  localStorage.removeItem('activeSession');
  
  // Reset all stores to initial state
  sessionStore.reset();
  chatStore.reset();
  patientStore.reset();
  
  // Navigate to home page
  router.push('/');
};



// Session restoration for patient info display (evaluation page only)
const restoreSessionInfo = async () => {
  console.log('[DebriefingView] Restoring session info...');
  console.log('[DebriefingView] Current session state:', {
    user: sessionStore.user,
    isEstablished: sessionStore.isEstablished,
    userRole: sessionStore.userRole,
    targetPatientId: sessionStore.targetPatientId,
    patient: patientStore.patientInfo,
    hasPatientInfo: patientStore.hasPatientInfo
  });
  
  // If stores already have user and patient data, no need to restore
  if (sessionStore.user && patientStore.hasPatientInfo) {
    console.log('[DebriefingView] Session already has user and patient info');
    return;
  }
  
  // Try to restore from localStorage (without affecting active session state)
  const savedSession = localStorage.getItem('activeSession');
  if (savedSession) {
    try {
      const { sessionId } = JSON.parse(savedSession);
      console.log('[DebriefingView] Found saved session ID:', sessionId);
      
      if (sessionId) {
        await loadSessionDataFromApi(sessionId);
      }
    } catch (error) {
      console.error('[DebriefingView] Failed to restore session info:', error);
    }
  } else {
    console.log('[DebriefingView] No saved session found');
  }
};

// Initialize
onMounted(async () => {
  await restoreSessionInfo();
  loadDebriefingData();
  
  // Load font size from localStorage
  const savedFontSize = localStorage.getItem('chatFontSize');
  if (savedFontSize) {
    fontSize.value = parseInt(savedFontSize, 10);
  }
  
  // Listen for font size changes
  window.addEventListener('fontSizeChanged', () => {
    const newFontSize = localStorage.getItem('chatFontSize');
    if (newFontSize) {
      fontSize.value = parseInt(newFontSize, 10);
    }
  });
});
</script>

<style scoped>
.debriefing-content {
  max-width: 1200px;
  margin: 0 auto;
}

blockquote {
  border-left: 4px solid rgb(var(--v-theme-primary));
  font-style: italic;
}

.v-timeline {
  padding-left: 0;
}

@media print {
  .no-print {
    display: none !important;
  }
  
  .v-btn,
  .v-footer,
  button {
    display: none !important;
  }
}
</style>
