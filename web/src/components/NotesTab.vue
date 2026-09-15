<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, type Pin } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import EmailDialog from './EmailDialog.vue'

const props = defineProps<{ talkId: string }>()
const lesson = useLessonStore()
const ui = useUiStore()
const emailOpen = ref(false)
const editing = ref<number | null>(null)
const editNote = ref('')

const status = computed(() => (lesson.saving ? 'Saving…' : lesson.savedAt ? 'Saved' : ''))

function print() {
  window.open(api.exportUrl(props.talkId), '_blank', 'noopener')
}

function move(p: Pin, dir: -1 | 1) {
  const ids = lesson.pins.map((x) => x.id)
  const i = ids.indexOf(p.id)
  const j = i + dir
  if (j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  lesson.reorder(ids)
}

function startEdit(p: Pin) {
  editing.value = p.id
  editNote.value = p.note
}
async function saveEdit(p: Pin) {
  await lesson.patchPin(p.id, { note: editNote.value })
  editing.value = null
}

function openSource(p: Pin) {
  if (p.kind === 'scripture' && p.scripture_ref) ui.openScripture(p.scripture_ref)
  else if (p.ref_talk_id) ui.openTalk(p.ref_talk_id, p.ref_paragraph_id != null ? undefined : null)
}

function kindLabel(p: Pin) {
  return p.kind === 'scripture' ? 'Scripture' : p.kind === 'quote' ? 'Quote' : p.kind === 'talk' ? 'Talk' : 'Note'
}
</script>

<template>
  <div class="notes-tab">
    <section>
      <div class="row between">
        <h3>Notes</h3>
        <span class="faint small">{{ status }}</span>
      </div>
      <textarea
        :value="lesson.notes"
        rows="10"
        placeholder="Main message, discussion questions, an outline… Markdown works here."
        @input="lesson.setNotes(($event.target as HTMLTextAreaElement).value)"
      ></textarea>
    </section>

    <section>
      <div class="row between">
        <h3>Pinned references</h3>
        <div class="row">
          <button class="small" @click="print">Print</button>
          <button class="small" @click="emailOpen = true">Email…</button>
        </div>
      </div>
      <p v-if="!lesson.pins.length" class="empty">
        Nothing pinned yet. Pin a talk, a passage, or a selected quote from the reader, search results, or an AI answer.
      </p>
      <ul v-else class="pins">
        <li v-for="(p, i) in lesson.pins" :key="p.id" class="pin">
          <div class="row between">
            <div class="kind small">{{ kindLabel(p) }}</div>
            <div class="row ctl">
              <button class="quiet small" :disabled="i === 0" @click="move(p, -1)" aria-label="Move up">↑</button>
              <button class="quiet small" :disabled="i === lesson.pins.length - 1" @click="move(p, 1)" aria-label="Move down">↓</button>
              <button class="quiet small" @click="lesson.removePin(p.id)">Remove</button>
            </div>
          </div>
          <div class="pin-body">
            <button v-if="p.kind === 'scripture'" class="ref" @click="openSource(p)">{{ p.scripture_ref }}</button>
            <button v-if="p.kind === 'talk' && p.ref_talk" class="link" @click="openSource(p)">{{ p.ref_talk.title }}</button>
            <blockquote v-if="p.text && p.kind !== 'talk'" class="serif" :class="{ clamp: p.kind !== 'note' }">{{ p.text }}</blockquote>
            <div v-if="p.ref_talk && p.kind !== 'talk'" class="talk-meta">
              <button class="link small" @click="openSource(p)">{{ p.ref_talk.title }}</button>, {{ p.ref_talk.speaker }}, {{ p.ref_talk.conference }}
            </div>
            <div v-else-if="p.ref_talk" class="talk-meta">{{ p.ref_talk.speaker }}, {{ p.ref_talk.conference }}</div>
            <div v-if="editing === p.id" class="row">
              <input v-model="editNote" type="text" placeholder="Why this matters for the lesson" @keydown.enter="saveEdit(p)" />
              <button class="small" @click="saveEdit(p)">Save</button>
            </div>
            <button v-else class="quiet small notebtn" @click="startEdit(p)">
              {{ p.note || 'Add a note' }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <EmailDialog v-if="emailOpen" :talk-id="talkId" @close="emailOpen = false" />
  </div>
</template>

<style scoped>
.notes-tab section + section {
  margin-top: 1.5rem;
}
h3 {
  font-size: var(--fs-2);
  margin-bottom: 0.4rem;
}
.pins {
  list-style: none;
  margin: 0;
  padding: 0;
}
.pin {
  border-left: 3px solid var(--gold);
  padding: 0.5rem 0.75rem 0.6rem;
  margin: 0.6rem 0;
  background: var(--paper-2);
}
.kind {
  color: var(--gold-2);
  font-weight: 600;
}
.ctl button {
  padding: 0.1rem 0.4rem;
}
.pin-body blockquote {
  margin: 0.3rem 0;
  font-size: 1rem;
  line-height: 1.5;
}
.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 5;
  line-clamp: 5;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.link {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--blue-2);
  font-family: var(--serif);
  font-weight: 600;
  text-align: left;
}
.link.small {
  font-family: var(--sans);
  font-weight: 400;
}
.link:hover {
  text-decoration: underline;
  background: transparent;
}
.notebtn {
  color: var(--ink-2);
  padding-left: 0;
  text-align: left;
  white-space: normal;
}
</style>
