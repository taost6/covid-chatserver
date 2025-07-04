<template>
  <v-overlay v-model="visible" class="align-center justify-center" persistent>
    <div class="text-center">
      <v-progress-circular 
        indeterminate 
        :size="size" 
        :color="color" 
        :width="width"
      ></v-progress-circular>
      <div class="text-center mt-4 text-white">
        <div class="text-h6 font-weight-medium">{{ title }}</div>
        <div v-if="subtitle" class="text-body-2 mt-1 text-grey-lighten-1">{{ subtitle }}</div>
      </div>
      <v-progress-linear 
        v-if="showProgress && progress !== null"
        :model-value="progress"
        :color="color"
        class="mt-4"
        height="6"
        rounded
      ></v-progress-linear>
    </div>
  </v-overlay>
</template>

<script setup lang="ts">
import { computed } from 'vue';

interface Props {
  modelValue: boolean;
  title: string;
  subtitle?: string;
  size?: string | number;
  color?: string;
  width?: string | number;
  showProgress?: boolean;
  progress?: number | null;
}

const props = withDefaults(defineProps<Props>(), {
  size: 64,
  color: 'primary',
  width: 4,
  showProgress: false,
  progress: null,
});

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value)
});
</script>