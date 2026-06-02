<template>
  <a-config-provider :theme="{ token: { colorPrimary: '#1677ff' } }">
    <router-view />
  </a-config-provider>
</template>

<script setup lang="ts">
// App root component
</script>

<style>
html, body, #app {
  height: 100%;
  margin: 0;
  padding: 0;
}
</style>