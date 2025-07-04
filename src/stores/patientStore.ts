import { defineStore } from 'pinia';
import type { PatientInfo } from '@/types';

interface PatientState {
  availablePatientIds: string[];
  selectedPatientId: string | null;
  patientInfo: PatientInfo | null;
  isLoading: boolean;
}

export const usePatientStore = defineStore('patient', {
  state: (): PatientState => ({
    availablePatientIds: [],
    selectedPatientId: null,
    patientInfo: null,
    isLoading: false,
  }),

  getters: {
    hasPatientInfo: (state): boolean => 
      state.patientInfo !== null,
    
    patientName: (state): string => 
      state.patientInfo?.name || '',
    
    patientAge: (state): number | null => 
      state.patientInfo?.age || null,
  },

  actions: {
    setAvailablePatientIds(ids: string[]) {
      this.availablePatientIds = ids;
    },

    setSelectedPatientId(id: string | null) {
      this.selectedPatientId = id;
    },

    setPatientInfo(info: PatientInfo | null) {
      this.patientInfo = info;
    },

    setLoading(loading: boolean) {
      this.isLoading = loading;
    },

    clearPatientInfo() {
      this.selectedPatientId = null;
      this.patientInfo = null;
    },

    reset() {
      this.availablePatientIds = [];
      this.selectedPatientId = null;
      this.patientInfo = null;
      this.isLoading = false;
    },
  },
});