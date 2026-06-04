<template>
  <a-empty :description="description || 'No data available'">
    <template v-if="$slots.extra" #children>
      <slot name="extra" />
    </template>
  </a-empty>
</template>

<script setup lang="ts">
defineProps<{ description?: string }>()
</script>
