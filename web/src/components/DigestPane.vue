<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, type Digest, type TalkDetail } from '../api'
import { useLessonStore } from '../stores/lesson'

const props = defineProps<{ talk: TalkDetail }>()
const emit = defineEmits<{ (e: 'goto', paragraphIdx: number): void; (e: 'ask', text: string): void }>()

const lesson = useLessonStore()
const digest = ref<Digest | null>(null)
const loading = ref(false)
const generating = ref(false)
const error = ref<string | null>(null)
const configured = ref<boolean | null>(null)

watch(
  () => props.talk.id,
  async (id) => {
    digest.value = null
    error.value = null
    loading.value = true
    try {
      const [d, s] = await Promise.all([api.digest(id), api.settings()])
      digest.value = d
      const prov = String(s.ai_provider)
      configured.value = prov === 'anthropic' ? Boolean(s.anthropic_api_key_set) : Boolean(s.ollama_model)
    } catch (e: any) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

async function generate() {
  generating.value = true
  error.value = null
  try {
    digest.value = await api.generateDigest(props.talk.id)
  } catch (e: any) {
    error.value = e.message
  } finally {
    generating.value = false
  }
}

const paraIdById = computed(() => new Map(props.talk.paragraphs.map((p) => [p.idx, p.id])))

function pinQuote(q: Digest['key_quotes'][number]) {
  lesson.addPin({
    kind: 'quote',
    ref_talk_id: props.talk.id,
    ref_paragraph_id: q.paragraph != null ? paraIdById.value.get(q.paragraph) ?? null : null,
    text: q.text,
    note: q.why,
  })
}

function pinQuestion(q: Digest['questions'][number]) {
  lesson.addPin({ kind: 'note', text: q.question, note: `Discussion question (${q.kind})` })
}

function askAbout(q: Digest['questions'][number]) {
  emit('ask', `Help me prepare to lead a discussion on this question from the talk:\n\n“${q.question}”\n\nWhat in the talk, the scriptures it cites, or other conference talks would help the quorum think about it?`)
}

const kindLabel: Record<string, string> = { opening: 'Opening', discussion: 'Discussion', application: 'Application' }
const grouped = computed(() => {
  const out: Record<string, Digest['questions']> = { opening: [], discussion: [], application: [] }
  for (const q of digest.value?.questions ?? []) (out[q.kind] ?? out.discussion).push(q)
  return out
})
</script>

<template>
  <div class="digest">
    <div v-if="loading" class="muted">Loading…</div>

    <div v-else-if="!digest" class="start">
      <h3>Essence of the talk</h3>
      <p class="muted">
        Generate a reader's digest: the central message, the main observations, quotations worth reading aloud, and
        discussion questions for the quorum. It is created once and kept with the talk.
      </p>
      <div v-if="configured === false" class="notice">
        This needs an AI provider. Add an Anthropic API key or an Ollama model in <RouterLink to="/settings">Settings</RouterLink>.
      </div>
      <button v-else class="primary" :disabled="generating" @click="generate">
        {{ generating ? 'Reading the talk…' : 'Generate digest' }}
      </button>
      <div v-if="error" class="notice error small">{{ error }}</div>
    </div>

    <template v-else>
      <div class="cols">
        <section class="col">
          <h3>Essence</h3>
          <p class="essence serif">{{ digest.essence }}</p>

          <h3>Main points</h3>
          <ol class="points">
            <li v-for="(m, i) in digest.main_points" :key="i">
              <span>{{ m.point }}</span>
              <button v-if="m.paragraph != null" class="quiet small goto" @click="emit('goto', m.paragraph)" title="Show in the talk">¶{{ m.paragraph }}</button>
            </li>
          </ol>

          <h3>Worth reading aloud</h3>
          <ul class="quotes">
            <li v-for="(q, i) in digest.key_quotes" :key="i">
              <blockquote class="serif">“{{ q.text }}”</blockquote>
              <div class="row between small">
                <span class="muted">{{ q.why }}</span>
                <span class="row">
                  <button v-if="q.paragraph != null" class="quiet small" @click="emit('goto', q.paragraph)">¶{{ q.paragraph }}</button>
                  <button class="quiet small" @click="pinQuote(q)">Pin</button>
                </span>
              </div>
            </li>
          </ul>
        </section>

        <section class="col">
          <h3>Questions for the quorum</h3>
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
      </div>

      <footer class="row between small faint">
        <span>Digest by {{ digest.provider }} · {{ digest.model }} · {{ digest.created_at.slice(0, 10) }}</span>
        <span class="row">
          <button class="quiet small" :disabled="generating" @click="generate">{{ generating ? 'Regenerating…' : 'Regenerate' }}</button>
        </span>
      </footer>
      <div v-if="error" class="notice error small">{{ error }}</div>
    </template>
  </div>
</template>

<style scoped>
.digest {
  padding-top: 0.25rem;
}
h3 {
  font-size: var(--fs-2);
  margin: 0.9rem 0 0.4rem;
}
h3:first-child {
  margin-top: 0;
}
.start {
  max-width: 60ch;
}
.start .notice,
.start button {
  margin-top: 0.75rem;
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
.essence {
  font-size: 1.08rem;
  line-height: 1.6;
}
.points {
  margin: 0;
  padding-left: 1.3rem;
}
.points li {
  margin-bottom: 0.45rem;
  line-height: 1.45;
}
.goto {
  margin-left: 0.35rem;
  color: var(--gold-2);
  padding: 0 0.3rem;
}
.quotes {
  list-style: none;
  margin: 0;
  padding: 0;
}
.quotes li {
  border-left: 3px solid var(--gold);
  padding: 0.35rem 0.75rem 0.4rem;
  margin-bottom: 0.7rem;
  background: var(--paper-2);
}
.quotes blockquote {
  margin: 0 0 0.25rem;
  font-size: 1.02rem;
  line-height: 1.5;
}
.qgroup {
  margin-bottom: 0.9rem;
}
.qkind {
  color: var(--gold-2);
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.questions {
  list-style: none;
  margin: 0;
  padding: 0;
}
.questions li {
  padding: 0.45rem 0 0.55rem;
  border-bottom: 1px solid var(--rule);
}
.questions li:last-child {
  border-bottom: 0;
}
.q {
  font-size: 1.05rem;
  line-height: 1.45;
  margin-bottom: 0.15rem;
}
footer {
  margin-top: 1rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--rule);
}
</style>
