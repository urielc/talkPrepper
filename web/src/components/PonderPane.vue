<script setup lang="ts">
import { computed } from 'vue'
import type { SourceKind, Study } from '../api'
import { audienceWho, questionsHeading } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'

const props = defineProps<{ study: Study }>()
const emit = defineEmits<{ (e: 'ask', text: string): void }>()

const lesson = useLessonStore()
const ui = useUiStore()

const summary = computed(() => props.study.summary)
const kindLabel: Record<string, string> = { opening: 'Opening', discussion: 'Discussion', application: 'Application' }
const grouped = computed(() => {
  const out: Record<string, NonNullable<typeof summary.value>['ponder']> = { opening: [], discussion: [], application: [] }
  for (const q of summary.value?.ponder ?? []) (out[q.kind] ?? out.discussion).push(q)
  return out
})

const KIND_LABEL: Record<SourceKind, string> = {
  talk: 'Talk',
  manual: 'Manual',
  song: 'Song',
  scripture: 'Scripture',
  josephus: 'Josephus',
  apocrypha: 'Apocrypha',
}

type Question = NonNullable<typeof summary.value>['ponder'][number]
type Further = NonNullable<typeof summary.value>['further'][number]

function pinQuestion(q: Question) {
  lesson.addPin({ kind: 'note', text: q.question, note: q.note ? `${q.note} (${q.kind})` : q.kind })
}

function askAbout(q: Question) {
  const key = props.study.audience
  const topic = props.study.topic
  if (key === 'sacrament')
    emit('ask', `Help me use this prompt in my sacrament meeting talk on "${topic}":\n\n“${q.question}”\n\nWhat in the queued sources, the scriptures, or other talks would help me develop it?`)
  else if (key === 'personal')
    emit('ask', `Help me think through this question in my study of "${topic}":\n\n“${q.question}”\n\nWhat in the queued sources, the scriptures, or other talks would help me?`)
  else
    emit('ask', `Help me prepare to lead a discussion on "${topic}" with this question:\n\n“${q.question}”\n\nWhat in the queued sources, the scriptures, or other talks would help ${audienceWho(key)} think about it?`)
}

function pinFurther(f: Further) {
  if (f.kind === 'talk') lesson.addPin({ kind: 'talk', ref_talk_id: f.ref, note: f.why })
  else lesson.addPin({ kind: 'note', text: f.title, note: `${KIND_LABEL[f.kind]}: ${f.ref}. ${f.why}` })
}
function hasFurtherPin(f: Further): boolean {
  return f.kind === 'talk' && lesson.hasPin('talk', f.ref)
}
</script>

<template>
  <div class="ponder">
    <p v-if="!summary" class="muted">Questions and further material appear here once the summary is generated.</p>
    <div v-else class="cols">
      <section class="col">
        <h3>{{ questionsHeading(study.audience) }}</h3>
        <template v-for="kind in ['opening', 'discussion', 'application']" :key="kind">
          <div v-if="grouped[kind].length" class="qgroup">
            <div class="qkind small">{{ kindLabel[kind] }}</div>
            <ul class="questions">
              <li v-for="(q, i) in grouped[kind]" :key="i">
                <p class="q serif">{{ q.question }}</p>
                <p class="muted small">{{ q.note }}</p>
                <div class="row">
                  <button class="quiet small" @click="pinQuestion(q)">Pin</button>
                  <button class="quiet small" @click="askAbout(q)">Ask AI</button>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </section>

      <section class="col">
        <h3>Further material</h3>
        <p v-if="!summary.further.length" class="muted small">The AI found nothing further in the library to suggest.</p>
        <ul class="further">
          <li v-for="f in summary.further" :key="f.candidate_id">
            <span class="kind">{{ KIND_LABEL[f.kind] }}</span>
            <button class="link" @click="ui.openSource(f.kind, f.ref)">{{ f.title }}</button>
            <p class="muted small">{{ f.why }}</p>
            <div class="row">
              <button class="quiet small" @click="ui.openSource(f.kind, f.ref)">Preview</button>
              <button class="quiet small" :disabled="hasFurtherPin(f)" @click="pinFurther(f)">
                {{ hasFurtherPin(f) ? 'Pinned' : 'Pin' }}
              </button>
            </div>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.ponder {
  padding-top: 0.25rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 0.9rem 0 0.4rem;
}
h3:first-child {
  margin-top: 0;
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 2.5rem;
}
@media (max-width: 1100px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
.qgroup {
  margin-bottom: 0.9rem;
}
.qkind {
  color: var(--gold-2);
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.questions,
.further {
  list-style: none;
  margin: 0;
  padding: 0;
}
.questions li,
.further li {
  padding: 0.45rem 0 0.55rem;
  border-bottom: 1px solid var(--rule);
}
.questions li:last-child,
.further li:last-child {
  border-bottom: 0;
}
.q {
  font-size: 1.05rem;
  line-height: 1.45;
  margin-bottom: 0.15rem;
}
.kind {
  color: var(--gold-2);
  font-size: var(--fs-0);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-right: 0.4rem;
}
.link {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--blue-2);
  font: inherit;
  cursor: pointer;
  text-align: left;
}
.further p {
  margin: 0.15rem 0 0.2rem;
}
</style>
