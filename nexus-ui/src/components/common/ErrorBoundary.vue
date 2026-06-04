<template>
  <slot v-if="!hasError" />
  <a-result v-else status="error" title="Something went wrong" :sub-title="errorMessage">
    <template #extra>
      <a-button type="primary" @click="reset">Try Again</a-button>
    </template>
  </a-result>
</template>

<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((err: Error) => {
  hasError.value = true
  errorMessage.value = err.message
  return false
})

function reset() {
  hasError.value = false
  errorMessage.value = ''
}
</script>
