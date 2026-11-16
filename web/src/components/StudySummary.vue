<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, type AudienceKey, type SourceKind, type Study } from '../api'
import { useAuthStore } from '../stores/auth'
import { useLessonStore } from '../stores/lesson'
import { useTopicStore } from '../stores/topic'
import { useUiStore } from '../stores/ui'
import AudienceSelect from './AudienceSelect.vue'
import SummarizeDialog from './SummarizeDialog.vue'

const props = defineProps<{ study: Study }>()
const emit = defineEmits<{
  (e: 'updated', study: Study): void
  (e: 'audience', key: AudienceKey): void
}>()

const router = useRouter()
const ui = useUiStore()
const lesson = useLessonStore()
const auth = useAuthStore()
const topicStore = useTopicStore()

const KIND_LABEL: Record<SourceKind, string> = {
  talk: 'Talk',
  manual: 'Manual',
  song: 'Song',
  scripture: 'Scripture',
  josephus: 'Josephus',
  apocrypha: 'Apocrypha',
}

const summary = computed(() => props.study.summary)
const labelOf = computed(() => new Map((summary.value?.source_labels ?? []).map((s) => [s.label, s])))

const dialog = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const configured = ref<boolean | null>(null)
api.aiStatus().then((s) => (configured.value = s.configured)).catch(() => (configured.value = false))

async function regenerate(modifier: string) {
  busy.value = true
  error.value = null
  try {
    if (modifier.trim() !== props.study.modifier) await api.patchStudy(props.study.id, { modifier })
    emit('updated', await api.regenerateStudy(props.study.id))
    dialog.value = false
  } catch (e: any) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function deleteStudy() {
  if (!window.confirm(`Delete the study “${props.study.topic}” with its notes and pins?`)) return
  try {
    await api.deleteStudy(props.study.id)
    await lesson.loadMine()
    router.push('/lessons')
  } catch (e: any) {
    ui.toast(e.message || 'Could not delete the study', 'error')
  }
}

function editSources() {
  topicStore.edit(props.study)
  router.push({ path: '/lessons', query: { topic: props.study.topic, find: 'topic' } })
}

function pinQuote(q: NonNullable<typeof summary.value>['key_quotes'][number]) {
  const src = labelOf.value.get(q.source)
  if (src?.kind === 'talk') lesson.addPin({ kind: 'quote', ref_talk_id: src.ref, text: q.text, note: q.why })
  else lesson.addPin({ kind: 'note', text: q.text, note: `${src?.title ?? 'Source'}. ${q.why}` })
}

const scriptureCount = computed(() => summary.value?.scriptures.length ?? 0)
</script>

<template>
  <div class="study">
    <header class="head">
      <nav class="crumbs small"><RouterLink to="/lessons?find=topic">Topic studies</RouterLink></nav>
      <h1>{{ study.topic }}</h1>
      <div class="byline">
        <span>Topic study</span>
        <span class="muted">{{ study.sources.length }} {{ study.sources.length === 1 ? 'source' : 'sources' }}</span>
      </div>
      <div class="current-row">
        <AudienceSelect :model-value="study.audience" @change="emit('audience', $event)" />
        <button v-if="lesson.isMine(study.key)" class="small gold" title="Remove from my lessons" @click="lesson.removeMine(study.key)">
          In my lessons ✓
        </button>
        <button v-else class="small" @click="lesson.addMine(study.key)">Add to my lessons</button>
        <button class="small" @click="editSources">Edit sources</button>
        <button v-if="summary" class="small" @click="dialog = true">Regenerate</button>
        <button class="quiet small" title="Deletes this study with its notes and pins" @click="deleteStudy">Delete study</button>
      </div>
    </header>

    <div v-if="!summary" class="start">
      <p class="muted">
        There is no summary yet. The AI reads the queued sources and writes an overview, themes, quotations to read
        aloud, and questions.
      </p>
      <div v-if="configured === false" class="notice">
        <template v-if="auth.user?.is_admin">
          This needs an AI provider. Add an Anthropic API key or an Ollama model in <RouterLink to="/settings">Settings</RouterLink>.
        </template>
        <template v-else>The AI assistant is not set up yet. Ask the administrator.</template>
      </div>
      <button v-else class="primary" @click="dialog = true">Generate summary</button>
    </div>

    <template v-else>
      <p class="overview serif">{{ summary.overview }}</p>

      <section v-if="summary.themes.length">
        <h2>Themes</h2>
        <ol class="themes">
          <li v-for="(t, i) in summary.themes" :key="i">
            <h3>{{ t.heading }}</h3>
            <p>{{ t.body }}</p>
            <div v-if="t.sources.length" class="chips">
              <button
                v-for="s in t.sources"
                :key="s"
                class="chip"
                :title="labelOf.get(s)?.title"
                @click="labelOf.get(s) && ui.openSource(labelOf.get(s)!.kind, labelOf.get(s)!.ref)"
              >
                {{ labelOf.get(s)?.title ?? s }}
              </button>
            </div>
          </li>
        </ol>
      </section>

      <section v-if="summary.key_quotes.length">
        <h2>Worth reading aloud</h2>
        <ul class="quotes">
          <li v-for="(q, i) in summary.key_quotes" :key="i">
            <blockquote class="serif">“{{ q.text }}”</blockquote>
            <p class="muted small">
              <button class="chip" @click="labelOf.get(q.source) && ui.openSource(labelOf.get(q.source)!.kind, labelOf.get(q.source)!.ref)">
                {{ labelOf.get(q.source)?.title ?? q.source }}
              </button>
              {{ q.why }}
              <span v-if="!q.verified" class="warn" title="The AI's wording was not found word for word in the source">
                Check the wording against the source.
              </span>
            </p>
            <button class="quiet small" @click="pinQuote(q)">Pin</button>
          </li>
        </ul>
      </section>

      <section v-if="scriptureCount">
        <h2>Scriptures that bear on it</h2>
        <p class="refs">
          <button v-for="r in summary.scriptures" :key="r" class="ref" @click="ui.openScripture(r)">{{ r }}</button>
        </p>
      </section>

      <section>
        <h2>Sources</h2>
        <ol class="sources">
          <li v-for="s in summary.source_labels" :key="s.label">
            <span class="kind">{{ KIND_LABEL[s.kind] }}</span>
            <button class="link" @click="ui.openSource(s.kind, s.ref)">{{ s.title }}</button>
            <span v-if="s.trimmed" class="faint small">(shortened for the summary)</span>
          </li>
        </ol>
        <p v-if="summary.missing.length" class="notice small">
          Not found, so not summarized: {{ summary.missing.map((m) => m.title || m.ref).join('; ') }}.
        </p>
        <p v-if="study.sources.length !== summary.source_labels.length + summary.missing.length" class="notice small">
          The sources changed after this summary. Regenerate to include the change.
        </p>
      </section>

      <footer class="faint small">
        Summary by {{ summary.provider }} · {{ summary.model }}
        <template v-if="study.modifier"> · Instructions: {{ study.modifier }}</template>
      </footer>
    </template>

    <SummarizeDialog
      v-if="dialog"
      mode="regenerate"
      :initial-modifier="study.modifier"
      :busy="busy"
      :error="error"
      @submit="regenerate"
      @close="dialog = false"
    />
  </div>
</template>

<style scoped>
.crumbs {
  margin-bottom: 0.75rem;
  color: var(--ink-2);
}
h1 {
  font-size: var(--fs-5);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.15;
}
.byline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1rem;
  margin-top: 0.6rem;
  font-size: var(--fs-1);
}
.current-row {
  margin-top: 0.75rem;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 1rem;
}
.head {
  margin-bottom: 1.5rem;
}
.overview {
  font-size: 1.12rem;
  line-height: 1.6;
}
h2 {
  font-size: var(--fs-3);
  margin: 1.75rem 0 0.6rem;
}
.themes {
  margin: 0;
  padding-left: 1.3rem;
}
.themes li {
  margin-bottom: 1rem;
}
.themes h3 {
  font-size: var(--fs-2);
  margin-bottom: 0.15rem;
}
.themes p {
  margin: 0 0 0.35rem;
  line-height: 1.5;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}
.chip {
  border: 1px solid var(--rule-strong);
  border-radius: 999px;
  background: var(--paper-2);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--fs-0);
  padding: 0 0.55rem;
  cursor: pointer;
  max-width: 28ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip:hover {
  color: var(--blue-2);
  border-color: var(--blue-2);
}
.quotes {
  list-style: none;
  margin: 0;
  padding: 0;
}
.quotes li {
  border-left: 3px solid var(--gold);
  padding: 0.35rem 0.75rem 0.4rem;
  margin-bottom: 0.8rem;
  background: var(--paper-2);
}
.quotes blockquote {
  margin: 0 0 0.25rem;
  font-size: 1.05rem;
  line-height: 1.5;
}
.warn {
  color: var(--gold-2);
}
.refs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 0.8rem;
}
.sources {
  margin: 0;
  padding-left: 1.3rem;
}
.sources li {
  margin-bottom: 0.3rem;
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
.start {
  max-width: 60ch;
}
.start .notice,
.start button {
  margin-top: 0.75rem;
}
footer {
  margin-top: 1.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--rule);
}
</style>
