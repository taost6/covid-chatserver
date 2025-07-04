<template>
  <v-app style="height: 100vh; display: flex; flex-direction: column;">
    <v-main style="flex: 1 1 auto; overflow: scroll; display: flex; flex-direction: column;">
      <v-container fluid class="pa-md-4 pa-2 d-flex flex-column" style="flex: 1 1 auto; display: flex; flex-direction: column;">
        <!-- Header -->
        <AppHeader @toggle-drawer="drawer = !drawer" />

        <!-- Patient Info Panel -->
        <PatientInfoPanel />

        <!-- Chat Window -->
        <ChatWindow ref="chatWindow" />
      </v-container>
    </v-main>

    <!-- Message Input -->
    <MessageInput />

    <!-- Navigation Drawer -->
    <NavigationDrawer 
      v-model="drawer" 
      @registration-success="handleRegistrationSuccess"
      @end-session-with-debrief="confirmEndSessionDialog = true"
      @end-session-simple="confirmSimpleEndDialog = true"
    />

    <!-- Dialogs -->
    <v-dialog v-model="confirmEndSessionDialog" max-width="400">
      <v-card title="会話を終了しますか？" text="会話を終了し、AIによる評価を表示します。">
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="cancelEndSessionRequest">会話を続ける</v-btn>
          <v-btn color="primary" @click="submitDebriefingRequestHandler">評価を表示する</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    
    <v-dialog v-model="confirmSimpleEndDialog" max-width="400">
      <v-card title="会話を終了しますか？">
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="confirmSimpleEndDialog = false">続ける</v-btn>
          <v-btn color="error" @click="submitEndSessionRequest">終了する</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    
    <v-dialog v-model="toolCallConfirmDialog" max-width="450">
      <v-card title="会話の終了を検知しました" text="このまま評価へ進みますか？">
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="continueConversation">会話を続ける</v-btn>
          <v-btn color="primary" @click="proceedToDebriefing">評価へ進む</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    
    <!-- Debriefing Dialog -->
    <DebriefingDialog 
      v-model="debriefingDialog" 
      :debriefing-data="debriefingData" 
      @start-new-session="submitEndSessionRequest"
    />

    <!-- Loading Overlays -->
    <LoadingOverlay 
      v-model="sessionStore.isConnecting"
      :title="connectionLoadingTitle"
      subtitle="少々お待ちください"
    />
    
    <LoadingOverlay 
      v-model="sessionStore.isLoadingDebriefing"
      title="評価を生成しています..."
      subtitle="会話内容を分析中です"
    />
  </v-app>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useSessionStore } from '@/stores/sessionStore';
import { useChatStore } from '@/stores/chatStore';
import { usePatientStore } from '@/stores/patientStore';
import { useWebSocket } from '@/composables/useWebSocket';
import { useFocus } from '@/composables/useFocus';
import { useScrollToBottom } from '@/composables/useScrollToBottom';
import { api } from '@/utils/api';
import type { DebriefingData } from '@/types';

// Components
import AppHeader from '@/components/layout/AppHeader.vue';
import NavigationDrawer from '@/components/layout/NavigationDrawer.vue';
import MessageInput from '@/components/layout/MessageInput.vue';
import PatientInfoPanel from '@/components/features/PatientInfoPanel.vue';
import ChatWindow from '@/components/features/ChatWindow.vue';
import DebriefingDialog from '@/components/features/DebriefingDialog.vue';
import LoadingOverlay from '@/components/shared/LoadingOverlay.vue';

// Stores
const sessionStore = useSessionStore();
const chatStore = useChatStore();
const patientStore = usePatientStore();

// Focus management
const { focusTextarea } = useFocus();

// Scroll management
const { scrollToBottom } = useScrollToBottom();

// Component refs
const chatWindow = ref<InstanceType<typeof ChatWindow>>();

// Local state
const drawer = ref(false);
const confirmEndSessionDialog = ref(false);
const confirmSimpleEndDialog = ref(false);
const toolCallConfirmDialog = ref(false);
const debriefingDialog = ref(false);
const debriefingData = ref<DebriefingData | null>(null);

// Computed properties
const connectionLoadingTitle = computed(() => {
  const userRole = sessionStore.userRole;
  if (userRole === '保健師') {
    return '患者AIとの接続を準備中...';
  } else if (userRole === 'patient') {
    return '保健師AIとの接続を準備中...';
  }
  return 'AIとの接続を準備中...';
});

// WebSocket composable
const { connect, disconnect, sendDebriefingRequest, sendContinueConversation, sendEndSession } = useWebSocket({
  onMessage: (message) => {
    console.log('WebSocket message received:', message);
    // 相手の応答時にフォーカスを戻し、スクロールする
    if (message.msg_type === 'MessageForwarded' || message.msg_type === 'ConversationContinueAccepted') {
      setTimeout(() => {
        console.log('[App] WebSocket message received, focusing and scrolling');
        focusTextarea();
        scrollToBottom();
      }, 200);
    }
  },
  onEstablished: (data) => {
    console.log('Session established:', data);
    sessionStore.setConnecting(false); // Stop loading indicator
    sessionStore.saveToLocalStorage();
    // セッション確立時にフォーカス
    setTimeout(() => {
      focusTextarea();
    }, 200);
  },
  onSessionTerminated: () => {
    sessionClosed();
  },
  onDebriefingResponse: (data) => {
    debriefingData.value = data;
    sessionStore.setLoadingDebriefing(false); // Stop loading indicator
    debriefingDialog.value = true;
  },
  onToolCallDetected: () => {
    toolCallConfirmDialog.value = true;
  },
  onConversationContinueAccepted: () => {
    console.log('Conversation continue accepted');
    // 会話継続時にフォーカス
    setTimeout(() => {
      focusTextarea();
    }, 100);
  },
  onMessageRejected: (reason) => {
    console.error('Message rejected:', reason);
  },
});

// Event handlers
const handleRegistrationSuccess = async (data: { userId: string; sessionId: string; userName: string; userRole: string; patientId: string | null }) => {
  try {
    // Create user object with registration data
    const user = {
      userId: data.userId,
      sessionId: data.sessionId,
      userName: data.userName,
      role: data.userRole as 'patient' | '保健師',
      status: 'Waiting' as const,
      targetPatientId: data.patientId,
    };
    
    sessionStore.setUser(user);
    sessionStore.setSessionId(data.sessionId);
    
    // If user is 保健師, set patient info
    if (data.userRole === '保健師' && data.patientId) {
      patientStore.setSelectedPatientId(data.patientId);
    }
    
    // Start loading indicator
    sessionStore.setConnecting(true);
    
    // Connect WebSocket
    await connect(data.userId);
    
    // Stop loading indicator (will be stopped in onEstablished callback)
    // sessionStore.setConnecting(false);
    
    // Close drawer after successful registration
    drawer.value = false;
  } catch (error) {
    console.error('Registration success handler failed:', error);
    sessionStore.setConnecting(false);
  }
};

const sessionInitialized = () => {
  sessionStore.reset();
  chatStore.reset();
  patientStore.reset();
  debriefingDialog.value = false;
  debriefingData.value = null;
  toolCallConfirmDialog.value = false;
};

// Session management
const sessionClosed = () => {
  disconnect();
  console.log('Session closed');
};

// Dialog handlers
const cancelEndSessionRequest = () => {
  confirmEndSessionDialog.value = false;
};

const proceedToDebriefing = () => {
  toolCallConfirmDialog.value = false;
  drawer.value = false; // サイドバーを隠す
  sessionStore.setLoadingDebriefing(true);
  
  try {
    sendDebriefingRequest();
  } catch (error) {
    console.error('Failed to request debriefing:', error);
    sessionStore.setLoadingDebriefing(false);
  }
};

const continueConversation = () => {
  toolCallConfirmDialog.value = false;
  try {
    sendContinueConversation();
  } catch (error) {
    console.error('Failed to continue conversation:', error);
  }
};

const submitDebriefingRequestHandler = () => {
  confirmEndSessionDialog.value = false;
  drawer.value = false; // サイドバーを隠す
  sessionStore.setLoadingDebriefing(true);
  
  try {
    sendDebriefingRequest();
  } catch (error) {
    console.error('Failed to request debriefing:', error);
    sessionStore.setLoadingDebriefing(false);
  }
};

const submitEndSessionRequest = () => {
  confirmSimpleEndDialog.value = false;
  debriefingDialog.value = false;
  
  try {
    sendEndSession();
  } catch (error) {
    console.error('Failed to end session:', error);
  }
  
  sessionInitialized();
};

// Session restoration
const restoreSession = async () => {
  const savedSession = localStorage.getItem('activeSession');
  if (!savedSession) return;
  
  try {
    const { sessionId: storedSessionId, userId: oldUserId } = JSON.parse(savedSession);
    if (!storedSessionId || !oldUserId) return;
    
    const protocol = window.location.protocol.replace(':', '');
    const host = window.location.host;
    const url = `${protocol}://${host}/v1/session/${storedSessionId}`;
    
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const sessionData = await response.json();
    
    // Restore user data to session store
    const user = {
      userId: sessionData.user_id, // Use server's user_id
      sessionId: sessionData.session_id,
      userName: sessionData.user_name || '',
      role: sessionData.user_role || 'patient',
      status: 'Waiting' as const,
      targetPatientId: sessionData.patient_id || null,
    };
    
    sessionStore.setUser(user);
    sessionStore.setSessionId(sessionData.session_id);
    
    if (sessionData.interview_date) {
      sessionStore.setInterviewDate(sessionData.interview_date);
    }
    
    // Update localStorage with new user_id
    localStorage.setItem('activeSession', JSON.stringify({ 
      sessionId: sessionData.session_id, 
      userId: sessionData.user_id 
    }));
    
    // Restore chat history
    if (sessionData.chat_history) {
      chatStore.restoreMessages(sessionData.chat_history);
    }
    
    // Restore patient info if available
    if (sessionData.patient_info) {
      patientStore.setPatientInfo(sessionData.patient_info);
      patientStore.setSelectedPatientId(sessionData.patient_id);
    } else if (sessionData.patient_id) {
      // If patient_info is not available but patient_id is, set the ID and let PatientInfoPanel load details
      patientStore.setSelectedPatientId(sessionData.patient_id);
    }
    
    // Update user status to Established (since session was already active)
    user.status = 'Established';
    sessionStore.setUser(user);
    
    // Enable chat input since session is restored
    chatStore.setInputDisabled(false);
    
    // Reconnect WebSocket
    sessionStore.setConnecting(true);
    await connect(sessionData.user_id, true);
    
    // Close drawer since session is established
    drawer.value = false;
    
    console.log('Session restored successfully');
  } catch (error) {
    console.error('Session restoration failed:', error);
    sessionStore.setConnecting(false);
    localStorage.removeItem('activeSession');
    sessionStore.clearSession();
  }
};

// Initialization
onMounted(async () => {
  try {
    // If no saved session, user needs to register
    const savedSession = localStorage.getItem('activeSession');
    if (!savedSession) {
      // セッションがない場合は何もしない（NavigationDrawerが自動でモーダルを表示）
      return;
    }
    
    await restoreSession();
  } catch (error) {
    console.error('Initialization error:', error);
    // 復元に失敗した場合も何もしない（NavigationDrawerが自動でモーダルを表示）
  }
});
</script>

<style>
/* Global styles from App.vue */
/* ... (same as before) ... */
</style>