import { defineStore } from 'pinia'
import { ref } from 'vue'

export type Theme = 'system' | 'light' | 'dark'

export interface Toast {
  id: number
  text: string
  kind: 'ok' | 'error' | 'info'
}

let toastSeq = 0

export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>('system')
  try {
    const saved = localStorage.getItem('lp.theme') as Theme | null
    if (saved) theme.value = saved
  } catch {
    /* storage unavailable */
  }
  applyTheme(theme.value)

  function setTheme(t: Theme) {
    theme.value = t
    applyTheme(t)
    try {
      localStorage.setItem('lp.theme', t)
    } catch {
      /* ignore */
    }
  }

  // Reader drawer: a second talk opened on top of the workspace
  const drawerTalkId = ref<string | null>(null)
  const drawerParagraph = ref<number | null>(null)
  function openTalk(id: string, paragraphIdx: number | null = null) {
    drawerTalkId.value = id
    drawerParagraph.value = paragraphIdx
  }
  function closeDrawer() {
    drawerTalkId.value = null
    drawerParagraph.value = null
  }

  // Scripture panel: the passage being viewed
  const scriptureRef = ref<string | null>(null)
  function openScripture(refText: string) {
    scriptureRef.value = refText
  }
  function closeScripture() {
    scriptureRef.value = null
  }

  const toasts = ref<Toast[]>([])
  function toast(text: string, kind: Toast['kind'] = 'info', ms = 3500) {
    const id = ++toastSeq
    toasts.value.push({ id, text, kind })
    setTimeout(() => {
      toasts.value = toasts.value.filter((t) => t.id !== id)
    }, ms)
  }

  return {
    theme,
    setTheme,
    drawerTalkId,
    drawerParagraph,
    openTalk,
    closeDrawer,
    scriptureRef,
    openScripture,
    closeScripture,
    toasts,
    toast,
  }
})

function applyTheme(t: Theme) {
  const root = document.documentElement
  if (t === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', t)
}
