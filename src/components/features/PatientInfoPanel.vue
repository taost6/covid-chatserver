<template>
  <div class="d-flex flex-column" style="height: auto;">
    <v-expansion-panels 
      v-if="showPanel" 
      v-model="panelState" 
      style="flex: 1 1 auto; overflow-y: visible;"
    >
      <v-expansion-panel elevation="3" rounded="xl">
        <v-expansion-panel-title color="blue-lighten-5">
          <v-icon start>mdi-account-box-outline</v-icon>
          患者情報・シチュエーション
        </v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-list density="compact">
            <v-list-item 
              v-if="showStaffInfo && sessionStore.userName" 
              class="bg-blue-lighten-5 rounded-lg mb-3 pa-3"
            >
              <div class="font-weight-bold text-blue-darken-4 mb-2">担当者</div>
              <div>{{ sessionStore.userName }}</div>
            </v-list-item>
            
            <v-list-item 
              v-if="sessionStore.interviewDate" 
              class="bg-yellow-lighten-5 rounded-lg mb-3 pa-3"
            >
              <div class="font-weight-bold text-orange-darken-4 mb-2">調査日（本日）</div>
              <div>{{ sessionStore.interviewDate }}</div>
            </v-list-item>
            
            <v-list-item 
              v-if="patientStore.hasPatientInfo" 
              class="bg-green-lighten-5 rounded-lg pa-3"
            >
              <div class="font-weight-bold text-green-darken-4">基本情報</div>
              <div>
                <span class="text-grey-darken-1">氏名:</span> 
                {{ patientStore.patientInfo?.name }}
              </div>
              <div>
                <span class="text-grey-darken-1">年齢・性別:</span> 
                {{ patientStore.patientInfo?.age }}歳 {{ patientStore.patientInfo?.gender }}
              </div>
              <div>
                <span class="text-grey-darken-1">生年月日:</span> 
                {{ patientStore.patientInfo?.birthDate }}
              </div>
              <div>
                <span class="text-grey-darken-1">居住地:</span> 
                {{ patientStore.patientInfo?.residence }}
              </div>
            </v-list-item>
            
            <!-- Commented out sections from original App.vue -->
            <!-- <v-list-item class="bg-purple-lighten-5 rounded-lg mb-3 pa-3">
                <div class="font-weight-bold text-purple-darken-4 mb-2">感染・発症</div>
                <div><span class="text-grey-darken-1">感染日:</span> {{ patientInfo.infectionDate }}</div>
                <div><span class="text-grey-darken-1">発症日:</span> {{ patientInfo.onsetDate }}</div>
            </v-list-item> -->
            <!-- <v-list-item class="bg-amber-lighten-5 rounded-lg pa-3">
              <div class="font-weight-bold text-amber-darken-4 mb-2">患者の特徴</div>
              <div class="text-caption text-grey-darken-3">{{ patientInfo.profile }}</div>
            </v-list-item> -->
          </v-list>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue';
import { useSessionStore } from '@/stores/sessionStore';
import { usePatientStore } from '@/stores/patientStore';
import { api } from '@/utils/api';

interface Props {
  showStaffInfo?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  showStaffInfo: false,
});

const sessionStore = useSessionStore();
const patientStore = usePatientStore();

const panelState = ref<number | undefined>(undefined);

const showPanel = computed(() => {
  // For debriefing page with staff info, show panel if we have user or patient info
  if (props.showStaffInfo) {
    return sessionStore.user || patientStore.hasPatientInfo;
  }
  // For regular chat page, require established session
  return (sessionStore.userRole === '保健師' || sessionStore.userRole === '傍聴者') && sessionStore.isEstablished;
});

// Load patient details when a patient is selected
watch(
  () => patientStore.selectedPatientId,
  async (patientId) => {
    console.log('[PatientInfoPanel] selectedPatientId changed:', patientId);
    if (patientId) {
      try {
        patientStore.setLoading(true);
        console.log('[PatientInfoPanel] Loading patient details for ID:', patientId);
        const patientInfo = await api.getPatientDetails(patientId);
        console.log('[PatientInfoPanel] Patient info loaded:', patientInfo);
        patientStore.setPatientInfo(patientInfo);
      } catch (error) {
        console.error('Failed to load patient details:', error);
        patientStore.setPatientInfo(null);
      } finally {
        patientStore.setLoading(false);
      }
    }
  },
  { immediate: true }
);

// Load patient info when target patient ID is available
watch(
  () => sessionStore.targetPatientId,
  async (patientId) => {
    console.log('[PatientInfoPanel] targetPatientId changed:', patientId);
    if (patientId) {
      patientStore.setSelectedPatientId(patientId);
    }
  },
  { immediate: true }
);

onMounted(() => {
  // Initialize panel state - expanded by default, especially for debriefing page
  panelState.value = 0;
});
</script>

<style scoped>
/* Patient info panel styles */
</style>