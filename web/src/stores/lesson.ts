import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Lesson, type Pin, type TalkSummary } from '../api'
import { useUiStore } from './ui'

export const useLessonStore = defineStore('lesson', () => {
  const talkId = ref<string | null>(null)
  const notes = ref('')
  const pins = ref<Pin[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const savedAt = ref<string | null>(null)

  // The lesson being prepared right now (one per app, stored server-side)
  const current = ref<TalkSummary | null>(null)
  const currentLoaded = ref(false)
  async function loadCurrent() {
    try {
      current.value = (await api.currentTalk()).talk
    } finally {
      currentLoaded.value = true
    }
  }
  async function setCurrent(id: string | null) {
    current.value = (await api.setCurrentTalk(id)).talk
    ui().toast(id ? 'Marked as your current lesson' : 'Current lesson cleared', 'ok', 1800)
  }

  async function load(id: string) {
    if (talkId.value === id && !loading.value) return
    loading.value = true
    talkId.value = id
    try {
      const l: Lesson = await api.lesson(id)
      if (talkId.value !== id) return
      notes.value = l.notes_md
      pins.value = l.pins
      savedAt.value = l.updated_at
    } finally {
      loading.value = false
    }
  }

  let timer: ReturnType<typeof setTimeout> | null = null
  function setNotes(text: string) {
    notes.value = text
    if (timer) clearTimeout(timer)
    timer = setTimeout(saveNotes, 700)
  }

  async function saveNotes() {
    if (!talkId.value) return
    saving.value = true
    try {
      const l = await api.saveNotes(talkId.value, notes.value)
      savedAt.value = l.updated_at
    } finally {
      saving.value = false
    }
  }

  const ui = () => useUiStore()

  async function addPin(pin: Partial<Pin> & { kind: Pin['kind'] }) {
    if (!talkId.value) return
    try {
      pins.value = await api.addPin(talkId.value, pin)
      ui().toast('Pinned', 'ok', 1800)
    } catch (e: any) {
      ui().toast(e.message || 'Could not pin', 'error')
    }
  }

  function hasPin(kind: Pin['kind'], key: string): boolean {
    return pins.value.some((p) =>
      kind === 'scripture' ? p.kind === 'scripture' && p.scripture_ref === key : p.kind === kind && p.ref_talk_id === key,
    )
  }

  async function patchPin(id: number, body: { text?: string; note?: string }) {
    if (!talkId.value) return
    pins.value = await api.patchPin(talkId.value, id, body)
  }

  async function removePin(id: number) {
    if (!talkId.value) return
    pins.value = await api.deletePin(talkId.value, id)
  }

  async function reorder(ids: number[]) {
    if (!talkId.value) return
    pins.value = await api.reorderPins(talkId.value, ids)
  }

  return { talkId, notes, pins, loading, saving, savedAt, current, currentLoaded, loadCurrent, setCurrent, load, setNotes, saveNotes, addPin, hasPin, patchPin, removePin, reorder }
})
