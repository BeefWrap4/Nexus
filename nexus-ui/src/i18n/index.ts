import { createI18n } from 'vue-i18n'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'

const messages = {
  'zh-CN': zhCN,
  'en-US': enUS
}

// 从localStorage读取用户偏好,否则检测浏览器语言
const getLocale = () => {
  const saved = localStorage.getItem('locale')
  if (saved && ['zh-CN', 'en-US'].includes(saved)) {
    return saved
  }
  return navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US'
}

const i18n = createI18n({
  legacy: false, // 使用Composition API
  locale: getLocale(),
  fallbackLocale: 'en-US',
  messages
})

export default i18n
