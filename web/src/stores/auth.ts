import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, setUnauthorizedHandler, type User } from '../api'
import { router } from '../router'
import { useLessonStore } from './lesson'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loaded = ref(false)

  async function load() {
    try {
      user.value = await api.me()
    } catch {
      user.value = null
    } finally {
      loaded.value = true
    }
  }

  async function login(email: string, password: string) {
    user.value = await api.login(email, password)
    await useLessonStore().loadMine()
  }

  async function setPassword(token: string, password: string) {
    user.value = await api.setPassword(token, password)
    await useLessonStore().loadMine()
  }

  async function logout() {
    try {
      await api.logout()
    } finally {
      user.value = null
      useLessonStore().reset()
      router.push({ name: 'login' })
    }
  }

  // Any 401 from the API means the session ended: drop local state and show the login screen.
  setUnauthorizedHandler(() => {
    if (user.value) {
      user.value = null
      useLessonStore().reset()
      router.push({ name: 'login', query: { next: router.currentRoute.value.fullPath } })
    }
  })

  return { user, loaded, load, login, setPassword, logout }
})
