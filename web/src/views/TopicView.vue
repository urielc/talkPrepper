<script setup lang="ts">
import { RouterLink, useRoute, useRouter } from 'vue-router'
import TopicStudy from '../components/TopicStudy.vue'

const route = useRoute()
const router = useRouter()
const initialTopic = typeof route.query.topic === 'string' ? route.query.topic : ''

/** Keeps the topic in the address so a reload or a shared link repeats the search. */
function onSearched(topic: string) {
  router.replace({ query: { ...route.query, topic } })
}
</script>

<template>
  <div class="topic-page">
    <nav class="crumbs small"><RouterLink to="/lessons">Lessons</RouterLink></nav>
    <h1>Study a topic</h1>
    <TopicStudy :initial-topic="initialTopic" @searched="onSearched" />
  </div>
</template>

<style scoped>
.topic-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.25rem 1.5rem 3rem;
}
h1 {
  margin: 0.25rem 0 1rem;
}
@media (max-width: 600px) {
  .topic-page {
    padding: 1rem 1rem 2.5rem;
  }
}
</style>
