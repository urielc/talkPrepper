<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Paragraph, TalkDetail } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'

const props = defineProps<{
  talk: TalkDetail
  scrollTo?: number | null
  compact?: boolean
}>()
const emit = defineEmits<{ (e: 'ask', text: string): void }>()

const ui = useUiStore()
const lesson = useLessonStore()
const root = ref<HTMLElement | null>(null)

interface Segment {
  text: string
  ref?: string
}

function segments(p: Paragraph): Segment[] {
  const out: Segment[] = []
  let pos = 0
  const refs = [...p.refs].sort((a, b) => a.start - b.start)
  const seen = new Set<string>()
  for (const r of refs) {
    const key = `${r.start}:${r.end}`
    if (seen.has(key) || r.start < pos) continue
    seen.add(key)
    if (r.start > pos) out.push({ text: p.text.slice(pos, r.start) })
    out.push({ text: p.text.slice(r.start, r.end), ref: r.ref })
    pos = r.end
  }
  if (pos < p.text.length) out.push({ text: p.text.slice(pos) })
  return out
}

const body = computed(() => props.talk.paragraphs.filter((p) => !p.is_note))
const notes = computed(() => props.talk.paragraphs.filter((p) => p.is_note))

// Which paragraph is the byline? Skip rendering "By Elder X" as body text when it duplicates the speaker.
const bodyStart = computed(() => {
  const first = body.value[0]
  if (first && /^(By|Presented by)\s/.test(first.text) && first.text.length < 90) return 1
  return 0
})

// Short opening lines without terminal punctuation are the speaker's role or a kicker, not prose.
function isKicker(p: Paragraph, i: number): boolean {
  return i < 2 && p.text.length < 110 && !/[.!?”"]$/.test(p.text.trim())
}

// ---- text selection toolbar
const sel = ref<{ text: string; paragraphId: number; x: number; y: number } | null>(null)

function onMouseUp() {
  setTimeout(() => {
    const s = window.getSelection()
    if (!s || s.isCollapsed || !root.value) {
      sel.value = null
      return
    }
    const text = s.toString().trim()
    if (text.length < 3) {
      sel.value = null
      return
    }
    const anchor = s.anchorNode
    const para = anchor && (anchor.nodeType === 1 ? (anchor as Element) : anchor.parentElement)?.closest('[data-pid]')
    if (!para || !root.value.contains(para)) {
      sel.value = null
      return
    }
    const rect = s.getRangeAt(0).getBoundingClientRect()
    const host = root.value.getBoundingClientRect()
    sel.value = {
      text,
      paragraphId: Number((para as HTMLElement).dataset.pid),
      x: Math.min(Math.max(rect.left - host.left + rect.width / 2, 90), host.width - 90),
      y: rect.top - host.top - 8,
    }
  }, 0)
}
function clearSel() {
  sel.value = null
}
function pinQuote() {
  if (!sel.value) return
  lesson.addPin({ kind: 'quote', ref_talk_id: props.talk.id, ref_paragraph_id: sel.value.paragraphId, text: sel.value.text })
  window.getSelection()?.removeAllRanges()
  sel.value = null
}
function askAbout() {
  if (!sel.value) return
  emit('ask', sel.value.text)
  window.getSelection()?.removeAllRanges()
  sel.value = null
}

onMounted(() => document.addEventListener('selectionchange', onSelChange))
onBeforeUnmount(() => document.removeEventListener('selectionchange', onSelChange))
function onSelChange() {
  const s = window.getSelection()
  if (!s || s.isCollapsed) sel.value = null
}

watch(
  () => [props.talk.id, props.scrollTo],
  async () => {
    if (props.scrollTo == null) return
    await nextTick()
    const el = root.value?.querySelector(`[data-idx="${props.scrollTo}"]`) as HTMLElement | null
    el?.scrollIntoView({ block: 'center' })
    el?.classList.add('flash')
    setTimeout(() => el?.classList.remove('flash'), 1600)
  },
  { immediate: true },
)
</script>

<template>
  <article ref="root" class="reader" :class="{ compact }" @mouseup="onMouseUp" @keyup="onMouseUp">
    <div v-if="sel" class="seltools" :style="{ left: sel.x + 'px', top: sel.y + 'px' }">
      <button class="small" @click.stop="pinQuote">Pin quote</button>
      <button class="small" @click.stop="askAbout">Ask about this</button>
      <button class="small quiet" @click.stop="clearSel" aria-label="Dismiss">×</button>
    </div>

    <div class="body">
      <p v-for="(p, i) in body.slice(bodyStart)" :key="p.id" :data-pid="p.id" :data-idx="p.idx" :class="{ kicker: isKicker(p, i) }">
        <template v-for="(s, i) in segments(p)" :key="i">
          <button
            v-if="s.ref"
            class="ref"
            :class="{ active: ui.scriptureRef === s.ref }"
            @click="ui.openScripture(s.ref!)"
            :title="`Open ${s.ref}`"
          >
            {{ s.text }}
          </button>
          <template v-else>{{ s.text }}</template>
        </template>
      </p>
    </div>

    <section v-if="notes.length" class="notes">
      <h3>Notes</h3>
      <ol>
        <li v-for="p in notes" :key="p.id" :data-pid="p.id" :data-idx="p.idx">
          <template v-for="(s, i) in segments(p)" :key="i">
            <button v-if="s.ref" class="ref" :class="{ active: ui.scriptureRef === s.ref }" @click="ui.openScripture(s.ref!)">
              {{ s.text }}
            </button>
            <template v-else>{{ s.text }}</template>
          </template>
        </li>
      </ol>
    </section>
  </article>
</template>

<style scoped>
.reader {
  position: relative;
  font-family: var(--serif);
  font-size: 1.125rem;
  line-height: 1.68;
  max-width: var(--reader-width);
}
.reader.compact {
  font-size: 1.05rem;
  line-height: 1.6;
}
.body p {
  margin: 0 0 1.05em;
}
.body p.kicker {
  font-family: var(--sans);
  font-size: var(--fs-1);
  color: var(--ink-2);
  margin-bottom: 1.5em;
}
.body p.flash,
.notes li.flash {
  background: var(--gold-mark);
  transition: background 1.2s ease;
}
.notes {
  margin-top: 2.5rem;
  padding-top: 1rem;
  border-top: 1px solid var(--rule);
  font-size: 0.9rem;
  line-height: 1.5;
  color: var(--ink-2);
}
.notes h3 {
  font-size: var(--fs-1);
  margin-bottom: 0.5rem;
  color: var(--ink-2);
}
.notes ol {
  padding-left: 1.5rem;
  margin: 0;
}
.notes li {
  margin-bottom: 0.35rem;
}
.notes .ref {
  border-bottom-width: 1px;
}
.seltools {
  position: absolute;
  transform: translate(-50%, -100%);
  display: flex;
  gap: 0.25rem;
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius);
  padding: 0.25rem;
  box-shadow: var(--shadow-pop);
  z-index: 5;
  font-family: var(--sans);
}
</style>
