<script setup lang="ts">
import { ref, watch } from 'vue'
import { api, type TalkDetail, type TalkSummary } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import TalkListItem from './TalkListItem.vue'

const props = defineProps<{ talk: TalkDetail }>()
const ui = useUiStore()
const lesson = useLessonStore()

const shared = ref<{ ref: string; count: number; talks: TalkSummary[] }[]>([])
const open = ref<Set<string>>(new Set())
const loading = ref(false)

watch(
  () => props.talk.id,
  async (id) => {
    loading.value = true
    open.value = new Set()
    try {
      shared.value = await api.sharedScriptures(id)
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

function toggle(r: string) {
  const s = new Set(open.value)
  s.has(r) ? s.delete(r) : s.add(r)
  open.value = s
}
</script>

<template>
  <div>
    <p v-if="!talk.scriptures.length" class="empty">No scripture references were detected in this talk.</p>
    <template v-else>
      <p class="muted small">Click a reference to read it; expand to see other talks that cite it.</p>
      <ul class="result-list">
        <li v-for="s in shared" :key="s.ref">
          <div class="row between">
            <button class="ref big" :class="{ active: ui.scriptureRef === s.ref }" @click="ui.openScripture(s.ref)">{{ s.ref }}</button>
            <div class="row">
              <button class="quiet small" :disabled="lesson.hasPin('scripture', s.ref)" @click="lesson.addPin({ kind: 'scripture', scripture_ref: s.ref })">
                {{ lesson.hasPin('scripture', s.ref) ? 'Pinned' : 'Pin' }}
              </button>
              <button class="quiet small" @click="toggle(s.ref)">
                {{ s.count }} other {{ s.count === 1 ? 'talk' : 'talks' }} {{ open.has(s.ref) ? '▴' : '▾' }}
              </button>
            </div>
          </div>
          <ul v-if="open.has(s.ref)" class="sub">
            <li v-if="!s.talks.length" class="muted small">No other talk cites this passage.</li>
            <li v-for="t in s.talks" :key="t.id">
              <TalkListItem :talk="t" :aside="t.mentions && t.mentions > 1 ? `${t.mentions} mentions` : undefined" />
            </li>
          </ul>
        </li>
      </ul>
      <div v-if="loading && !shared.length" class="muted">Loading…</div>
    </template>

    <section v-if="talk.cites.length || talk.cited_by.length" class="cites">
      <h3>Talk citations</h3>
      <template v-if="talk.cites.length">
        <p class="muted small">This talk cites</p>
        <ul class="result-list">
          <li v-for="(c, i) in talk.cites" :key="i">
            <TalkListItem v-if="c.talk" :talk="c.talk" />
            <div v-else class="muted">
              “{{ c.title }}” <span class="faint">({{ c.year }}, not in the index)</span>
            </div>
          </li>
        </ul>
      </template>
      <template v-if="talk.cited_by.length">
        <p class="muted small">Cited by</p>
        <ul class="result-list">
          <li v-for="t in talk.cited_by" :key="t.id"><TalkListItem :talk="t" /></li>
        </ul>
      </template>
    </section>
  </div>
</template>

<style scoped>
.ref.big {
  font-family: var(--serif);
  font-size: var(--fs-2);
  font-weight: 600;
}
.sub {
  list-style: none;
  padding: 0.5rem 0 0 1rem;
  margin: 0.25rem 0 0;
  border-left: 2px solid var(--rule);
}
.sub > li {
  padding: 0.5rem 0;
}
.cites {
  margin-top: 2rem;
}
.cites h3 {
  font-size: var(--fs-2);
  margin-bottom: 0.5rem;
}
.cites p.small {
  margin: 0.75rem 0 0.25rem;
}
</style>
