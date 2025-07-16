import { defineStore } from 'pinia';
import type { PatientInfo } from '@/types';

interface PatientState {
  availablePatientIds: string[];
  availablePatients: PatientInfo[];
  selectedPatientId: string | null;
  patientInfo: PatientInfo | null;
  isLoading: boolean;
}

export const usePatientStore = defineStore('patient', {
  state: (): PatientState => ({
    availablePatientIds: [],
    availablePatients: [],
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
    
    patientSelectItems: (state) => 
      state.availablePatients.map(patient => ({
        title: `${patient.id}: ${patient.name} (${patient.age}歳 ${patient.gender})`,
        value: patient.id
      })),
  },

  actions: {
    setAvailablePatientIds(ids: string[]) {
      this.availablePatientIds = ids;
    },

    setAvailablePatients(patients: PatientInfo[]) {
      this.availablePatients = patients;
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
      this.availablePatients = [];
      this.selectedPatientId = null;
      this.patientInfo = null;
      this.isLoading = false;
    },
  },
});