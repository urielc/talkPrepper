<script setup lang="ts">
import { ref } from 'vue'
import type { TalkDetail } from '../api'
import { useLessonStore } from '../stores/lesson'
import { useUiStore } from '../stores/ui'
import CollapsibleSection from './CollapsibleSection.vue'
import RelatedSection from './RelatedSection.vue'
import ScripturesSection from './ScripturesSection.vue'
import SearchSection, { type SearchOutcome } from './SearchSection.vue'
import TalkListItem from './TalkListItem.vue'
import { safeSnippet } from '../utils/markdown'

defineProps<{ talk: TalkDetail }>()
const ui = useUiStore()
const lesson = useLessonStore()

const outcome = ref<SearchOutcome | null>(null)
const relatedCount = ref<number | null>(null)
</script>

<template>
  <div class="research">
    <SearchSection @results="outcome = $event" />

    <CollapsibleSection
      v-if="outcome"
      :title="`Results for “${outcome.query}”`"
      :count="outcome.results.length + outcome.verses.length"
      storage-key="results"
    >
      <template #actions>
        <button class="quiet small" @click="outcome = null">Clear</button>
      </template>
      <p v-if="outcome.mode !== outcome.requestedMode" class="muted small">
        Meaning-based search is unavailable until embeddings are built; showing exact-word results.
      </p>
      <template v-if="outcome.verses.length">
        <p class="sub muted small">Scriptures</p>
        <ul class="result-list">
          <li v-for="v in outcome.verses" :key="v.ref" class="row between">
            <div class="grow">
              <button class="ref" @click="ui.openScripture(v.ref)">{{ v.ref }}</button>
              <div class="serif muted small" v-html="safeSnippet(v.snippet)"></div>
            </div>
            <button class="quiet small" :disabled="lesson.hasPin('scripture', v.ref)" @click="lesson.addPin({ kind: 'scripture', scripture_ref: v.ref })">
              {{ lesson.hasPin('scripture', v.ref) ? 'Pinned' : 'Pin' }}
            </button>
          </li>
        </ul>
        <p class="sub muted small">Talks</p>
      </template>
      <p v-if="!outcome.results.length" class="empty small">No talks matched. Try fewer words, or switch to “Meaning”.</p>
      <ul v-else class="result-list">
        <li v-for="h in outcome.results" :key="h.talk_id">
          <TalkListItem :talk="h.talk!" :snippets="h.snippets" />
        </li>
      </ul>
    </CollapsibleSection>

    <CollapsibleSection title="Related talks" :count="relatedCount" storage-key="related">
      <RelatedSection :talk-id="talk.id" @count="relatedCount = $event" />
    </CollapsibleSection>

    <CollapsibleSection title="Scriptures cited" :count="talk.scriptures.length" storage-key="scriptures">
      <ScripturesSection :talk="talk" />
    </CollapsibleSection>
  </div>
</template>

<style scoped>
.research {
  min-height: 0;
}
.sub {
  margin: 0.5rem 0 0.15rem;
}
</style>
