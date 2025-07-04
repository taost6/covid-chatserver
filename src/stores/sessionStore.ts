import { defineStore } from 'pinia';
import type { User, UserStatus, UserRole, SessionInfo } from '@/types';

interface SessionState {
  user: User | null;
  sessionId: string | null;
  isConnected: boolean;
  ws: WebSocket | null;
  interviewDate: string | null;
}

export const useSessionStore = defineStore('session', {
  state: (): SessionState => ({
    user: null,
    sessionId: null,
    isConnected: false,
    ws: null,
    interviewDate: null,
  }),

  getters: {
    isEstablished: (state): boolean => 
      state.user?.status === 'Established' && state.isConnected,
    
    userRole: (state): UserRole | null => 
      state.user?.role || null,
    
    userId: (state): string | null => 
      state.user?.userId || null,
    
    userName: (state): string | null => 
      state.user?.userName || null,
    
    targetPatientId: (state): string | null => 
      state.user?.targetPatientId || null,
  },

  actions: {
    setUser(user: User) {
      this.user = user;
    },

    updateUserStatus(status: UserStatus) {
      if (this.user) {
        this.user.status = status;
      }
    },

    setSessionId(sessionId: string) {
      this.sessionId = sessionId;
      if (this.user) {
        this.user.sessionId = sessionId;
      }
    },

    setConnection(ws: WebSocket, isConnected: boolean = true) {
      this.ws = ws;
      this.isConnected = isConnected;
    },

    setInterviewDate(date: string) {
      this.interviewDate = date;
    },

    saveToLocalStorage() {
      if (this.sessionId && this.userId) {
        const sessionInfo: SessionInfo = {
          sessionId: this.sessionId,
          userId: this.userId,
        };
        localStorage.setItem('activeSession', JSON.stringify(sessionInfo));
      }
    },

    loadFromLocalStorage(): SessionInfo | null {
      const stored = localStorage.getItem('activeSession');
      if (stored) {
        try {
          return JSON.parse(stored) as SessionInfo;
        } catch {
          return null;
        }
      }
      return null;
    },

    clearSession() {
      this.user = null;
      this.sessionId = null;
      this.isConnected = false;
      this.ws = null;
      this.interviewDate = null;
      localStorage.removeItem('activeSession');
    },

    reset() {
      this.clearSession();
    },
  },
});