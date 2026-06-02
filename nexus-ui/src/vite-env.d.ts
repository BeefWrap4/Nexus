/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module 'ant-design-vue/dist/reset.css' {
  const content: string
  export default content
}

declare module '@vue-flow/core/dist/style.css' {
  const content: string
  export default content
}

declare module '@vue-flow/core/dist/theme-default.css' {
  const content: string
  export default content
}
