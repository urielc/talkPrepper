import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Lesson, type MyLesson, type Pin } from '../api'
import { useUiStore } from './ui'

export const useLessonStore = defineStore('lesson', () => {
  const talkId = ref<string | null>(null)
  const notes = ref('')
  const pins = ref<Pin[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const savedAt = ref<string | null>(null)

  // Talks this user is working on (shown on the landing page and in the top bar)
  const mine = ref<MyLesson[]>([])
  const mineLoaded = ref(false)
  async function loadMine() {
    try {
      mine.value = await api.myLessons()
    } finally {
      mineLoaded.value = true
    }
  }
  function isMine(id: string): boolean {
    return mine.value.some((m) => m.talk.id === id)
  }
  async function addMine(id: string) {
    mine.value = await api.addMyLesson(id)
    ui().toast('Added to my lessons', 'ok', 1800)
  }
  async function removeMine(id: string) {
    mine.value = await api.removeMyLesson(id)
    ui().toast('Removed from my lessons', 'ok', 1800)
  }
  function reset() {
    talkId.value = null
    notes.value = ''
    pins.value = []
    mine.value = []
    mineLoaded.value = false
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

  return { talkId, notes, pins, loading, saving, savedAt, mine, mineLoaded, loadMine, isMine, addMine, removeMine, reset, load, setNotes, saveNotes, addPin, hasPin, patchPin, removePin, reorder }
})
