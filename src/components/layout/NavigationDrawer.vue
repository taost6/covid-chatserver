<template>
  <v-navigation-drawer v-model="localDrawer" location="right" temporary width="360">
    <v-toolbar title="操作メニュー">
      <v-spacer></v-spacer>
      <v-btn icon="mdi-close" @click="closeDrawer"></v-btn>
    </v-toolbar>
    <v-divider></v-divider>
    <v-list nav dense>
      <v-list-item title="ロール">
        <v-dialog v-model="registrationDialog" persistent max-width="400px">
          <template v-slot:activator="{ props: activatorProps }">
            <v-btn 
              density="default" 
              block 
              class="pa-2" 
              :disabled="sessionStore.isEstablished" 
              v-bind="activatorProps"
            >
              {{ roleText }}
            </v-btn>
          </template>
          <v-card prepend-icon="mdi mdi-account-alert" title="ロールの選択" text="必須項目を入力して開始してください。">
            <template v-slot:actions>
              <v-form v-model="formValid" @submit.prevent="handleRegistration" class="w-100 pa-4">
                <v-text-field 
                  v-model="userName" 
                  label="お名前" 
                  :rules="[rules.required]" 
                  required
                ></v-text-field>
                <v-radio-group v-model="selectedRole" :rules="[rules.required]" label="あなたのロール">
                  <v-radio label="保健師" value="保健師"></v-radio>
                  <v-radio label="患者" value="患者"></v-radio>
                </v-radio-group>
                <v-select 
                  v-if="selectedRole === '保健師'" 
                  v-model="selectedPatientId" 
                  label="担当する患者ID" 
                  :items="patientStore.availablePatientIds" 
                  :rules="[rules.required]" 
                  required
                ></v-select>
                <div class="d-flex justify-end">
                  <v-btn type="submit" class="pa-2 elevation-2" :disabled="!formValid">開始</v-btn>
                </div>
              </v-form>
            </template>
          </v-card>
        </v-dialog>
      </v-list-item>
      
      <v-list-item 
        v-if="sessionStore.userRole === '保健師'" 
        id="submitEndOfSessionWithDebrief" 
        class="mt-2 mr-2" 
        prepend-icon="mdi-file-document-check-outline" 
        variant="outlined"
      >
        <v-btn @click="$emit('end-session-with-debrief')">会話の終了と評価</v-btn>
      </v-list-item>
      
      <v-list-item 
        v-if="sessionStore.userRole === '患者'" 
        id="submitEndOfSessionSimple" 
        class="mt-2 mr-2" 
        prepend-icon="mdi-close-circle-outline" 
        variant="outlined"
      >
        <v-btn @click="$emit('end-session-simple')">会話の終了</v-btn>
      </v-list-item>
      
      <v-divider thickness="2" color="block" class="my-3"></v-divider>
      
      <v-list-item title="文字の大きさ">
        <v-slider 
          v-model="fontSize" 
          @end="changeFontSize" 
          :ticks="{0:'小',1:'中',2:'大'}" 
          min="0" 
          max="2" 
          step="1" 
          show-ticks="always" 
          tick-size="2"
        ></v-slider>
      </v-list-item>
      
      <v-list-item>
        <v-checkbox 
          label="改行で送信" 
          v-model="submitWithEnter" 
          density="compact" 
          hide-details="true"
        ></v-checkbox>
      </v-list-item>
      
      <v-list-item>
        <v-checkbox 
          label="送信後クリア" 
          v-model="submitThenClear" 
          density="compact" 
          hide-details="true"
        ></v-checkbox>
      </v-list-item>
      
      <v-list-item 
        title="会話の最後へ" 
        prepend-icon="mdi-arrow-collapse-down" 
        @click="scrollToBottom"
      ></v-list-item>
      
      <v-divider class="my-2"></v-divider>
      
      <v-list-item 
        title="このページを印刷する" 
        prepend-icon="mdi-printer" 
        @click="printPage"
      ></v-list-item>
    </v-list>
  </v-navigation-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useSessionStore } from '@/stores/sessionStore';
import { usePatientStore } from '@/stores/patientStore';
import { api } from '@/utils/api';
import type { UserRole } from '@/types';

interface Props {
  modelValue: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  'registration-success': [data: { userId: string; sessionId: string; userName: string; userRole: string; patientId: string | null }];
  'end-session-with-debrief': [];
  'end-session-simple': [];
}>();

const router = useRouter();
const sessionStore = useSessionStore();
const patientStore = usePatientStore();

const localDrawer = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
});

const registrationDialog = ref(true);
const formValid = ref(false);
const userName = ref('');
const selectedRole = ref<UserRole | null>(null);
const selectedPatientId = ref<string | null>(null);
const fontSize = ref(1);
const submitWithEnter = ref(true);
const submitThenClear = ref(true);

const rules = {
  required: (value: string) => !!value || '必須項目です',
};

const roleText = computed(() => {
  if (!sessionStore.user || !sessionStore.isEstablished) return 'ロール選択';
  return sessionStore.user.role;
});

const closeDrawer = () => {
  localDrawer.value = false;
};

const handleRegistration = async () => {
  if (!formValid.value || !userName.value || !selectedRole.value) return;
  
  try {
    const userData = {
      user_name: userName.value,
      user_role: selectedRole.value,
      target_patient_id: selectedRole.value === '保健師' ? selectedPatientId.value! : undefined,
    };
    
    const result = await api.registerUser(userData);
    
    if (result.msg_type === 'RegistrationAccepted') {
      emit('registration-success', {
        userId: result.user_id,
        sessionId: result.session_id,
        userName: userName.value,
        userRole: selectedRole.value,
        patientId: selectedRole.value === '保健師' ? selectedPatientId.value : null,
      });
      registrationDialog.value = false;
    }
  } catch (error) {
    console.error('Registration failed:', error);
  }
};

const changeFontSize = () => {
  localStorage.setItem('chatFontSize', fontSize.value.toString());
};

const scrollToBottom = async () => {
  closeDrawer();
  await new Promise(resolve => setTimeout(resolve, 100));
  const mainContent = document.querySelector('.v-main');
  if (mainContent) {
    mainContent.scrollTop = mainContent.scrollHeight;
  }
};

const printPage = () => {
  // サイドバーを閉じる
  closeDrawer();
  // 印刷プレビューを表示
  setTimeout(() => {
    window.print();
  }, 100);
};

// Load patient IDs when drawer opens or registration dialog opens
watch([localDrawer, registrationDialog], async ([isDrawerOpen, isDialogOpen]) => {
  if ((isDrawerOpen || isDialogOpen) && patientStore.availablePatientIds.length === 0) {
    try {
      const patientIds = await api.getPatientIds();
      patientStore.setAvailablePatientIds(patientIds);
    } catch (error) {
      console.error('Failed to load patient IDs:', error);
    }
  }
});

// Load settings from localStorage
onMounted(async () => {
  const savedFontSize = localStorage.getItem('chatFontSize');
  if (savedFontSize) {
    fontSize.value = parseInt(savedFontSize, 10);
  }
  
  const savedSubmitWithEnter = localStorage.getItem('confSubmitWithEnter');
  if (savedSubmitWithEnter) {
    submitWithEnter.value = JSON.parse(savedSubmitWithEnter);
  }
  
  const savedSubmitThenClear = localStorage.getItem('confSubmitThenClear');
  if (savedSubmitThenClear) {
    submitThenClear.value = JSON.parse(savedSubmitThenClear);
  }
  
  // Show registration dialog if no established session
  registrationDialog.value = !sessionStore.isEstablished;
  
  // Load patient IDs on mount if needed
  if (!sessionStore.isEstablished && patientStore.availablePatientIds.length === 0) {
    try {
      const patientIds = await api.getPatientIds();
      patientStore.setAvailablePatientIds(patientIds);
    } catch (error) {
      console.error('Failed to load patient IDs on mount:', error);
    }
  }
});

// Watch for session establishment to close dialog
watch(() => sessionStore.isEstablished, (isEstablished) => {
  if (isEstablished) {
    registrationDialog.value = false;
  } else {
    // セッションが終了したら登録ダイアログを表示
    registrationDialog.value = true;
  }
});

// Save settings to localStorage
watch(submitWithEnter, (newValue) => {
  localStorage.setItem('confSubmitWithEnter', JSON.stringify(newValue));
});

watch(submitThenClear, (newValue) => {
  localStorage.setItem('confSubmitThenClear', JSON.stringify(newValue));
});
</script>

<style scoped>
/* Navigation drawer styles */
</style>