<template>
  <v-app>
    <router-view />
  </v-app>
</template>

<script setup lang="ts">
// Main App component with router
</script>

<style>
/* Global application styles */
* {
  box-sizing: border-box;
}

/* スマホ対応のViewport設定 */
html, body {
  height: 100%;
  height: 100vh;
  /* スマホのUIバーを考慮した高さ設定 */
  height: 100dvh; /* Dynamic viewport height */
  overflow: hidden;
}

/* Hide scrollbars but keep scrolling functionality */
html::-webkit-scrollbar,
body::-webkit-scrollbar {
  display: none;
}

/* Vuetify アプリケーションのスマホ対応 */
.v-application {
  height: 100vh !important;
  height: 100dvh !important; /* Dynamic viewport height */
}

.v-main {
  height: calc(100vh - 64px) !important; /* ヘッダーの高さを引く */
  height: calc(100dvh - 64px) !important;
  overflow-y: auto !important;
}

/* Application background */
.v-application {
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%) !important;
}

.v-main {
  background: transparent !important;
}

/* Global card styling */
.v-card {
  background: rgba(255, 255, 255, 0.9) !important;
  backdrop-filter: blur(10px) !important;
}

.v-toolbar {
  background: rgba(248, 250, 252, 0.95) !important;
  backdrop-filter: blur(10px) !important;
}

/* Print styles */
@media print {
  body {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }
  .v-navigation-drawer, .v-footer {
    display: none !important;
  }
  .v-application, .v-main, .v-container {
    height: auto !important;
    overflow: visible !important;
  }
}
</style>