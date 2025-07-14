import { ref, computed } from 'vue';
import { useSessionStore } from '@/stores/sessionStore';
import { useChatStore } from '@/stores/chatStore';
import type { WebSocketMessage, UserRole } from '@/types';

interface WebSocketOptions {
  onMessage?: (message: WebSocketMessage) => void;
  onEstablished?: (data: { session_id: string; interview_date?: string }) => void;
  onSessionTerminated?: () => void;
  onDebriefingResponse?: (data: any) => void;
  onToolCallDetected?: () => void;
  onConversationContinueAccepted?: () => void;
  onMessageRejected?: (reason: string) => void;
}

export function useWebSocket(options: WebSocketOptions = {}) {
  const sessionStore = useSessionStore();
  const chatStore = useChatStore();
  
  const isConnecting = ref(false);
  const connectionError = ref<string | null>(null);

  const isConnected = computed(() => sessionStore.isConnected);
  const connectionStatus = computed(() => {
    if (isConnecting.value) return 'connecting';
    if (sessionStore.isConnected) return 'connected';
    return 'disconnected';
  });

  function getWebSocketUrl(userId: string): string {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const host = window.location.host;
    return `${protocol}://${host}/v1/ws/${userId}`;
  }

  function connect(userId: string, isReconnection = false): Promise<void> {
    return new Promise((resolve, reject) => {
      if (sessionStore.ws) {
        sessionStore.ws.close();
      }

      isConnecting.value = true;
      connectionError.value = null;

      const url = getWebSocketUrl(userId);
      const ws = new WebSocket(url);

      ws.onopen = () => {
        isConnecting.value = false;
        sessionStore.setConnection(ws, true);
        
        // For reconnections, stop loading state immediately since session is already established
        if (isReconnection) {
          sessionStore.setConnecting(false);
          if (options.onMessage) {
            options.onMessage({
              msg_type: 'Reconnected',
            });
          }
        }
        
        resolve();
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          console.log('WS Received:', message);
          
          handleMessage(message);
          
          if (options.onMessage) {
            options.onMessage(message);
          }
        } catch (error) {
          console.error('WebSocket message parse error:', error);
        }
      };

      ws.onclose = () => {
        isConnecting.value = false;
        sessionStore.setConnection(ws, false);
        
        if (options.onSessionTerminated) {
          options.onSessionTerminated();
        }
      };

      ws.onerror = (error) => {
        isConnecting.value = false;
        connectionError.value = 'WebSocket接続でエラーが発生しました。';
        console.error('WebSocketエラー:', error);
        
        sessionStore.setConnection(ws, false);
        reject(new Error('WebSocket connection failed'));
      };
    });
  }

  function handleMessage(message: WebSocketMessage) {
    switch (message.msg_type) {
      case 'Established':
        if (message.session_id) {
          sessionStore.setSessionId(message.session_id);
          sessionStore.updateUserStatus('Established');
        }
        if (message.interview_date) {
          sessionStore.setInterviewDate(message.interview_date);
        }
        chatStore.setInputDisabled(false);
        
        if (options.onEstablished) {
          options.onEstablished({
            session_id: message.session_id!,
            interview_date: message.interview_date,
          });
        }
        break;

      case 'MessageForwarded':
        if (message.user_msg) {
          // user_msgが文字列でない場合の安全な処理
          let processedMessage: string;
          if (typeof message.user_msg === 'string') {
            processedMessage = message.user_msg;
          } else if (message.user_msg && typeof message.user_msg === 'object') {
            console.warn('[WebSocket] Received object message:', message.user_msg);
            processedMessage = JSON.stringify(message.user_msg);
          } else {
            processedMessage = String(message.user_msg || '');
          }
          
          // 傍聴者の場合は、AIの発言者に応じて表示を切り替える
          if (sessionStore.userRole === '傍聴者' && (message as any).ai_role) {
            const aiRole = (message as any).ai_role;
            if (aiRole === '保健師') {
              chatStore.addNurseAIMessage(processedMessage);
            } else if (aiRole === '患者') {
              chatStore.addPatientAIMessage(processedMessage);
            }
          } else {
            chatStore.addAssistantMessage(
              processedMessage, 
              sessionStore.userRole!
            );
          }
        }
        chatStore.setInputLocked(false);
        break;

      case 'SessionTerminated':
        if (options.onSessionTerminated) {
          options.onSessionTerminated();
        }
        break;

      case 'DebriefingResponse':
        if (options.onDebriefingResponse) {
          options.onDebriefingResponse(message.debriefing_data);
        }
        break;

      case 'ToolCallDetected':
        if (options.onToolCallDetected) {
          options.onToolCallDetected();
        }
        break;

      case 'ConversationContinueAccepted':
        chatStore.setInputLocked(false);
        if (options.onConversationContinueAccepted) {
          options.onConversationContinueAccepted();
        }
        break;

      case 'MessageRejected':
        if (message.reason) {
          chatStore.addSystemMessage(`システムエラー: ${message.reason}`);
        }
        chatStore.setInputLocked(false);
        
        if (options.onMessageRejected) {
          options.onMessageRejected(message.reason || 'Unknown error');
        }
        break;
    }
  }

  function sendMessage(message: Partial<WebSocketMessage>): void {
    if (!sessionStore.ws || !sessionStore.isConnected) {
      throw new Error('WebSocket is not connected');
    }

    sessionStore.ws.send(JSON.stringify(message));
  }

  function sendChatMessage(text: string): void {
    if (!sessionStore.sessionId || !sessionStore.userId) {
      throw new Error('Session not established');
    }

    chatStore.setInputLocked(true);
    chatStore.addUserMessage(text, sessionStore.userRole!);

    sendMessage({
      msg_type: 'MessageSubmitted',
      session_id: sessionStore.sessionId,
      user_id: sessionStore.userId,
      user_msg: text,
    });
  }

  function sendDebriefingRequest(): void {
    if (!sessionStore.sessionId || !sessionStore.userId) {
      throw new Error('Session not established');
    }

    sendMessage({
      msg_type: 'DebriefingRequest',
      session_id: sessionStore.sessionId,
      user_id: sessionStore.userId,
    });
  }

  function sendContinueConversation(): void {
    if (!sessionStore.sessionId || !sessionStore.userId) {
      throw new Error('Session not established');
    }

    sendMessage({
      msg_type: 'ContinueConversationRequest',
      session_id: sessionStore.sessionId,
      user_id: sessionStore.userId,
    });
  }

  function sendEndSession(): void {
    if (!sessionStore.sessionId || !sessionStore.userId) {
      throw new Error('Session not established');
    }

    sendMessage({
      msg_type: 'EndSessionRequest',
      session_id: sessionStore.sessionId,
      user_id: sessionStore.userId,
    });
  }

  function disconnect(): void {
    if (sessionStore.ws) {
      sessionStore.ws.close();
      sessionStore.setConnection(sessionStore.ws, false);
    }
  }

  return {
    // State
    isConnected,
    isConnecting: computed(() => isConnecting.value),
    connectionStatus,
    connectionError: computed(() => connectionError.value),

    // Actions
    connect,
    disconnect,
    sendMessage,
    sendChatMessage,
    sendDebriefingRequest,
    sendContinueConversation,
    sendEndSession,
  };
}