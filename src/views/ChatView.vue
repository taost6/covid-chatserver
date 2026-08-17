<template>
  <v-app class="chat-app">
    <v-main class="chat-main">
      <v-container fluid class="pa-md-4 pa-2 chat-container">
        <!-- Header -->
        <AppHeader @toggle-drawer="drawer = !drawer" />

        <!-- Patient Info Panel -->
        <PatientInfoPanel />

        <!-- Chat Window -->
        <ChatWindow 
          ref="chatWindow" 
          @continue-conversation="continueConversation"
          @proceed-to-debriefing="proceedToDebriefing"
        />
      </v-container>
    </v-main>

    <!-- Message Input (Fixed Footer) -->
    <MessageInput 
      class="chat-input-footer"
      @interrupt-session-with-debrief="confirmInterruptDialog = true" 
    />

    <!-- Navigation Drawer -->
    <NavigationDrawer
      v-model="drawer"
      :disable-registration="isCBTMode"
      @registration-success="handleRegistrationSuccess"
      @end-session-with-debrief="confirmEndSessionDialog = true"
      @end-session-simple="confirmSimpleEndDialog = true"
      @interrupt-session-with-debrief="confirmInterruptDialog = true"
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
    
    <v-dialog v-model="confirmInterruptDialog" max-width="400">
      <v-card title="対話を中断しますか？" text="現在の対話を中断し、AIによる評価を表示します。">
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="confirmInterruptDialog = false">対話を続行</v-btn>
          <v-btn color="warning" @click="submitInterruptRequestHandler">評価を実行</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    

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
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { useRouter } from 'vue-router';
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
import LoadingOverlay from '@/components/shared/LoadingOverlay.vue';

// Router
const router = useRouter();

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
// CBT文脈で開かれた場合はロール選択モーダルを抑制する
const isCBTMode = ref(!!sessionStorage.getItem('cbt_token'));
const confirmEndSessionDialog = ref(false);
const confirmSimpleEndDialog = ref(false);
const confirmInterruptDialog = ref(false);
const toolCallConfirmDialog = ref(false);
const debriefingData = ref<DebriefingData | null>(null);

// Rate limit notification timer
let rateLimitTimer: number | null = null;

// Computed properties
const connectionLoadingTitle = computed(() => {
  const userRole = sessionStore.userRole;
  if (userRole === '保健師') {
    return '患者との接続を準備中...';
  } else if (userRole === '患者') {
    return '保健師との接続を準備中...';
  } else if (userRole === '傍聴者') {
    return 'AI同士の対話を準備中...';
  }
  return '接続を準備中...';
});

// Rate limit notification handler
const handleRateLimitWait = (data: { wait_seconds: number; message: string }) => {
  // 傍聴者ロールの場合のみ表示
  if (sessionStore.userRole !== '傍聴者') {
    return;
  }
  
  // Clear existing timer first to prevent conflicts
  if (rateLimitTimer) {
    clearInterval(rateLimitTimer);
    rateLimitTimer = null;
  }
  
  // Set rate limit message in chat store
  chatStore.setRateLimitMessage(data.message, data.wait_seconds);
  
  // Start countdown timer
  rateLimitTimer = setInterval(() => {
    if (!chatStore.rateLimitMessage) {
      // Message was cleared externally, clean up timer
      if (rateLimitTimer) {
        clearInterval(rateLimitTimer);
        rateLimitTimer = null;
      }
      return;
    }
    
    const currentRemaining = chatStore.rateLimitMessage.remainingSeconds;
    const newRemaining = currentRemaining - 1;
    
    if (newRemaining <= 0) {
      chatStore.clearRateLimitMessage();
      if (rateLimitTimer) {
        clearInterval(rateLimitTimer);
        rateLimitTimer = null;
      }
    } else {
      chatStore.updateRateLimitTimer(newRemaining);
    }
  }, 1000);
};

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
    sessionStore.setDebriefingExists(true); // Mark debriefing as completed

    // CBTセッションの場合はCBT結果画面へ（リスク加重スコアを算出）
    const cbtToken = sessionStorage.getItem('cbt_token');
    if (cbtToken) {
      router.push({ name: 'cbt-result', params: { token: cbtToken } });
      return;
    }

    // 新評価系（IRT判定）: サーバがIRT判定を実行済みなので判定結果画面へ
    if (data && data.result_type === 'irt') {
      router.push({
        name: 'irt-result',
        params: { sessionId: sessionStore.sessionId || 'current' }
      });
      return;
    }

    // 旧評価系（総評レポート）: サーバが旧デブリーフィングを返した場合のみ従来の評価画面へ
    router.push({
      name: 'debriefing',
      params: {
        sessionId: sessionStore.sessionId || 'current',
        data: JSON.stringify(data)
      }
    });
  },
  onConversationEndChoices: () => {
    // No dialog needed - the system message will handle the UI
    console.log('Conversation end choices displayed in chat');
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
  onRateLimitWait: handleRateLimitWait,
});

// Event handlers
const handleRegistrationSuccess = async (data: { userId: string; sessionId: string; userName: string; userRole: string; patientId: string | null }) => {
  try {
    // Create user object with registration data
    const user = {
      userId: data.userId,
      sessionId: data.sessionId,
      userName: data.userName,
      role: data.userRole as 'patient' | '保健師' | '傍聴者',
      status: 'Waiting' as const,
      targetPatientId: data.patientId,
    };
    
    sessionStore.setUser(user);
    sessionStore.setSessionId(data.sessionId);
    
    // If user is 保健師 or 傍聴者, set patient info
    if ((data.userRole === '保健師' || data.userRole === '傍聴者') && data.patientId) {
      patientStore.setSelectedPatientId(data.patientId);
    }

    // Set debriefing exists status (default to false for new sessions)
    sessionStore.setDebriefingExists(false);
    
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
  cleanup(); // Clean up rate limit timer
  sessionStore.reset();
  chatStore.reset();
  patientStore.reset();
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
  // Check if debriefing already exists
  if (sessionStore.debriefingExists) {
    console.warn('Debriefing already exists for this session');
    // Redirect to existing debriefing page
    router.push({
      name: 'debriefing',
      params: {
        sessionId: sessionStore.sessionId || 'current'
      }
    });
    return;
  }

  // Called from system message button - no dialog to close
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
  // Called from system message button - no dialog to close
  try {
    sendContinueConversation();
  } catch (error) {
    console.error('Failed to continue conversation:', error);
  }
};

const submitDebriefingRequestHandler = () => {
  // Check if debriefing already exists
  if (sessionStore.debriefingExists) {
    console.warn('Debriefing already exists for this session');
    confirmEndSessionDialog.value = false;
    // Redirect to existing debriefing page
    router.push({
      name: 'debriefing',
      params: {
        sessionId: sessionStore.sessionId || 'current'
      }
    });
    return;
  }

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

const submitInterruptRequestHandler = () => {
  // Similar to submitDebriefingRequestHandler but for interrupting
  confirmInterruptDialog.value = false;
  drawer.value = false; // サイドバーを隠す
  sessionStore.setLoadingDebriefing(true);
  
  try {
    sendDebriefingRequest();
  } catch (error) {
    console.error('Failed to interrupt session:', error);
    sessionStore.setLoadingDebriefing(false);
  }
};

const submitEndSessionRequest = () => {
  confirmSimpleEndDialog.value = false;
  
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

    // Set debriefing exists status from restored session
    if (sessionData.debriefing_exists !== undefined) {
      sessionStore.setDebriefingExists(sessionData.debriefing_exists);
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
    
    // 傍聴者ロール（自動対話）の場合はセッションを破棄してロール選択モーダルを表示
    if (sessionData.user_role === '傍聴者') {
      console.log('Observer role session detected, destroying session and showing role selection modal');
      
      // セッションを破棄
      try {
        const destroyUrl = `${protocol}://${host}/v1/session/${sessionData.session_id}/destroy`;
        await fetch(destroyUrl, { method: 'POST' });
      } catch (error) {
        console.error('Failed to destroy observer session:', error);
      }
      
      // ローカルストレージとストアをクリア
      localStorage.removeItem('activeSession');
      sessionStore.clearSession();
      chatStore.reset();
      patientStore.reset();
      
      // ロール選択モーダルを表示するために早期リターン
      return;
    }
    
    // Update user status to Established (since session was already active)
    user.status = 'Established';
    sessionStore.setUser(user);
    
    // Enable chat input since session is restored
    chatStore.setInputDisabled(false);
    
    // Reconnect WebSocket
    sessionStore.setConnecting(true);
    await connect(sessionData.user_id, true);
    
    // Stop loading indicator after successful restoration
    sessionStore.setConnecting(false);
    
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

// Cleanup function
const cleanup = () => {
  if (rateLimitTimer) {
    clearInterval(rateLimitTimer);
    rateLimitTimer = null;
  }
  chatStore.clearRateLimitMessage();
};

// Initialization
// CBT文脈での自動登録（CBTタスク画面から遷移してきた場合）
const tryCBTAutoRegister = async (): Promise<boolean> => {
  const cbtToken = sessionStorage.getItem('cbt_token');
  const cbtPatientId = sessionStorage.getItem('cbt_patient_id');
  if (!cbtToken || !cbtPatientId) return false;

  // 前のセッションの状態を完全にクリアする（対話履歴・患者情報の混在を防ぐ）
  localStorage.removeItem('activeSession');
  sessionStore.reset();
  chatStore.reset();
  patientStore.reset();

  try {
    const result = await api.registerUser({
      user_name: `cbt:${cbtToken}`,
      user_role: '保健師',
      target_patient_id: String(cbtPatientId),
    });
    if (result.msg_type === 'RegistrationAccepted') {
      // CBTセッションIDを記録（CBTタスク画面での完了記録に使用）
      sessionStorage.setItem('cbt_session_id', result.session_id);
      await handleRegistrationSuccess({
        userId: result.user_id,
        sessionId: result.session_id,
        userName: `cbt:${cbtToken}`,
        userRole: '保健師',
        patientId: String(cbtPatientId),
      });
      return true;
    }
  } catch (error) {
    console.error('CBT auto-registration failed:', error);
  }
  return false;
};

onMounted(async () => {
  try {
    const cbtToken = sessionStorage.getItem('cbt_token');
    const cbtPatientId = sessionStorage.getItem('cbt_patient_id');
    const cbtSessionId = sessionStorage.getItem('cbt_session_id');
    const savedSession = localStorage.getItem('activeSession');

    // CBT文脈がある場合
    if (cbtToken && cbtPatientId) {
      // 進行中のCBTセッション（cbt_session_id が保存済みセッションと一致）なら復元
      if (cbtSessionId && savedSession) {
        try {
          const parsed = JSON.parse(savedSession);
          if (parsed?.sessionId === cbtSessionId) {
            await restoreSession();
            return;
          }
        } catch {
          /* パース失敗時は新規登録へフォールスルー */
        }
      }
      // 新規CBTタスク：古いセッションを破棄して保健師ロールで自動登録
      localStorage.removeItem('activeSession');
      const cbtRegistered = await tryCBTAutoRegister();
      if (cbtRegistered) return;
    }

    // 通常フロー：保存済みセッションがあれば復元
    if (savedSession) {
      await restoreSession();
      return;
    }

    // いずれもなければ何もしない（NavigationDrawerが自動でモーダルを表示）
  } catch (error) {
    console.error('Initialization error:', error);
    // 復元に失敗した場合も何もしない（NavigationDrawerが自動でモーダルを表示）
  }
});

// Cleanup on unmount
onUnmounted(() => {
  cleanup();
});
</script>

<style scoped>
/* ChatView specific mobile layout styles */
.chat-app {
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding-bottom: 80px; /* フッターの高さ分の余白 */
}

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 8px !important;
}

.chat-input-footer {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: white;
  border-top: 1px solid #e0e0e0;
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.1);
}

/* モバイル向けのViewport調整 */
@media screen and (max-width: 768px) {
  .chat-app {
    height: 100vh;
    height: 100dvh;
  }
  
  .chat-main {
    padding-bottom: 88px !important; /* モバイルでのフッター高さ調整 */
  }
  
  .chat-container {
    padding: 4px !important;
  }
}

/* iOS Safari対応 */
@supports (-webkit-touch-callout: none) {
  .chat-app {
    height: 100vh;
    height: -webkit-fill-available;
  }
  
  .chat-main {
    padding-bottom: 88px !important;
  }
}

</style>