import { defineStore } from 'pinia';
import { api } from '@/utils/api';

interface SessionLog {
  session_id: string;
  user_role: string;
  user_name: string;
  patient_id: string | null;
  started_at: string;
}

interface ChatLog {
  id: number;
  sender: string;
  role: string;
  ai_role?: string;
  message: string;
  created_at: string;
}

interface HistoryState {
  sessions: SessionLog[];
  currentSession: ChatLog[];
  isLoading: boolean;
  currentSessionId: string | null;
  tableState: {
    page: number;
    itemsPerPage: number;
  };
}

export const useHistoryStore = defineStore('history', {
  state: (): HistoryState => ({
    sessions: [],
    currentSession: [],
    isLoading: false,
    currentSessionId: null,
    tableState: {
      page: 1,
      itemsPerPage: 10,
    },
  }),

  getters: {
    formattedSessions: (state): SessionLog[] => 
      state.sessions.map(s => ({
        ...s,
        started_at: new Date(s.started_at).toLocaleString()
      })),
  },

  actions: {
    async fetchSessions() {
      this.isLoading = true;
      try {
        const protocol = window.location.protocol.replace(':', '');
        const host = window.location.host;
        const url = `${protocol}://${host}/v1/logs`;
        
        const response = await fetch(url, {
          headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        this.sessions = await response.json();
      } catch (error) {
        console.error('Failed to fetch sessions:', error);
        throw error;
      } finally {
        this.isLoading = false;
      }
    },

    async fetchSessionDetail(sessionId: string) {
      this.isLoading = true;
      this.currentSessionId = sessionId;
      
      try {
        const protocol = window.location.protocol.replace(':', '');
        const host = window.location.host;
        const url = `${protocol}://${host}/v1/logs/${sessionId}`;
        
        const response = await fetch(url, {
          headers: { 'Content-Type': 'application/json' }
        });
        
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        this.currentSession = await response.json();
      } catch (error) {
        console.error('Failed to fetch session detail:', error);
        throw error;
      } finally {
        this.isLoading = false;
      }
    },

    saveTableState() {
      localStorage.setItem('historyTablePage', JSON.stringify(this.tableState.page));
      localStorage.setItem('historyTableItemsPerPage', JSON.stringify(this.tableState.itemsPerPage));
    },

    loadTableState() {
      const savedPage = localStorage.getItem('historyTablePage');
      const savedItemsPerPage = localStorage.getItem('historyTableItemsPerPage');
      
      if (savedItemsPerPage) {
        this.tableState.itemsPerPage = JSON.parse(savedItemsPerPage);
      }
      
      if (savedPage) {
        const page = JSON.parse(savedPage);
        const totalPages = Math.ceil(this.sessions.length / this.tableState.itemsPerPage);
        if (page > 0 && page <= totalPages) {
          this.tableState.page = page;
        }
      }
    },

    setTablePage(page: number) {
      this.tableState.page = page;
      this.saveTableState();
    },

    setTableItemsPerPage(itemsPerPage: number) {
      this.tableState.itemsPerPage = itemsPerPage;
      this.saveTableState();
    },

    reset() {
      this.sessions = [];
      this.currentSession = [];
      this.isLoading = false;
      this.currentSessionId = null;
    },
  },
});