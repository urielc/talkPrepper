// Typed client for the FastAPI backend (same origin; Vite proxies /api in dev).

export interface Conference {
  id: string
  year: number
  month: number
  label: string
  url: string
  talk_count: number
}

export interface TalkSummary {
  id: string
  conference_id: string
  conference: string | null
  year: number | null
  speaker: string
  title: string
  url: string
  word_count: number
  has_lesson?: boolean
  mentions?: number
}

export interface ScriptureRefInline {
  ref: string
  book: string
  chapter: number
  verse_start: number | null
  verse_end: number | null
  start: number
  end: number
  raw: string
}

export interface Paragraph {
  id: number
  idx: number
  text: string
  is_note: boolean
  marker: number | null
  note_refs: { n: number; pos: number }[]
  refs: ScriptureRefInline[]
}

export interface Passage {
  ref: string
  book: string
  chapter: number
  verse_start: number | null
  verse_end: number | null
}

export interface TalkDetail extends TalkSummary {
  paragraphs: Paragraph[]
  scriptures: Passage[]
  cites: { talk: TalkSummary | null; title: string | null; year: number | null; month: number | null; raw: string }[]
  cited_by: TalkSummary[]
  prev: TalkSummary | null
  next: TalkSummary | null
  lesson: { has_notes: boolean; pin_count: number; mine: boolean }
}

export interface Hit {
  talk_id: string
  score: number
  snippets: string[]
  sources: string[]
  talk: TalkSummary | null
  shared_scriptures?: number
}

export interface Verse {
  book: string
  chapter: number
  verse: number
  text: string
  ref: string
}

export interface Lookup {
  ref: string
  book: string
  volume: string
  chapter: number
  verse_start: number | null
  verse_end: number | null
  chapters: number
  verses: Verse[]
}

export interface Pin {
  id: number
  talk_id: string
  kind: 'talk' | 'scripture' | 'quote' | 'note'
  ref_talk_id: string | null
  ref_paragraph_id: number | null
  scripture_ref: string | null
  text: string
  note: string
  ord: number
  created_at: string
  ref_talk: TalkSummary | null
}

export interface Lesson {
  talk_id: string
  notes_md: string
  updated_at: string | null
  pins: Pin[]
}

export interface ChatBlock {
  type: 'text' | 'tool' | 'error'
  text?: string
  id?: string
  name?: string
  input?: Record<string, unknown>
  summary?: string
  refs?: { type: 'talk' | 'scripture'; id?: string; ref?: string; title?: string; speaker?: string }[]
  preview?: string
}

export interface ChatMessage {
  id?: number
  role: 'user' | 'assistant'
  blocks: ChatBlock[]
  streaming?: boolean
}

export interface ChatSession {
  id: number
  talk_id: string
  title: string
  provider: string
  model: string
  created_at: string
  updated_at: string
  message_count?: number
  messages?: ChatMessage[]
}

export interface Digest {
  talk_id: string
  provider: string
  model: string
  created_at: string
  essence: string
  main_points: { point: string; paragraph: number | null }[]
  key_quotes: { text: string; paragraph: number | null; why: string }[]
  questions: { question: string; kind: 'opening' | 'discussion' | 'application'; note: string }[]
}

export interface User {
  id: number
  email: string
  name: string
  is_admin: boolean
  disabled: boolean
  has_password: boolean
  created_at: string
  last_login_at: string | null
}

export interface AdminUser extends User {
  invite_pending: boolean
}

export interface MyLesson {
  talk: TalkSummary
  added_at: string
  notes_len: number
  pin_count: number
  has_digest: boolean
  updated_at: string | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Called on any 401 from a non-auth endpoint; the auth store installs a redirect to /login. */
export let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(init.headers || {}) },
  })
  if (res.status === 401 && !path.startsWith('/auth/') && onUnauthorized) onUnauthorized()
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j)
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
const put = <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
const patch = <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
const del = <T>(path: string) => request<T>(path, { method: 'DELETE' })

export const api = {
  health: () => get<{ ok: boolean; has_users: boolean; index_ready: boolean; built_at: string | null; semantic: boolean }>('/health'),
  conferences: () => get<Conference[]>('/conferences'),
  conferenceTalks: (id: string) => get<TalkSummary[]>(`/conferences/${id}/talks`),
  talks: (q: string, conference?: string, limit = 50) =>
    get<TalkSummary[]>(`/talks?q=${encodeURIComponent(q)}${conference ? `&conference=${conference}` : ''}&limit=${limit}`),
  talk: (id: string) => get<TalkDetail>(`/talks/${id}`),
  related: (id: string, limit = 20) =>
    get<{ terms: string[]; results: Hit[]; semantic: boolean }>(`/talks/${id}/related?limit=${limit}`),
  sharedScriptures: (id: string) =>
    get<{ ref: string; count: number; talks: TalkSummary[] }[]>(`/talks/${id}/shared-scriptures`),
  search: (body: {
    q: string
    mode: 'hybrid' | 'keyword' | 'semantic'
    years?: [number, number]
    speaker?: string
    limit?: number
  }) =>
    post<{ query: string; mode: string; semantic_available: boolean; results: Hit[]; verses: (Verse & { snippet: string })[] }>(
      '/search',
      body,
    ),
  lookup: (ref: string) => get<Lookup>(`/scriptures/lookup?ref=${encodeURIComponent(ref)}`),
  lookupTalks: (ref: string, exclude?: string) =>
    get<{ ref: string; total: number; talks: TalkSummary[] }>(
      `/scriptures/lookup/talks?ref=${encodeURIComponent(ref)}${exclude ? `&exclude=${encodeURIComponent(exclude)}` : ''}`,
    ),
  chapter: (book: string, chapter: number) => get<Lookup>(`/scriptures/${encodeURIComponent(book)}/${chapter}`),

  digest: (id: string) => get<Digest | null>(`/talks/${id}/digest`),
  generateDigest: (id: string) => post<Digest>(`/talks/${id}/digest`),
  deleteDigest: (id: string) => del<{ ok: boolean }>(`/talks/${id}/digest`),

  myLessons: () => get<MyLesson[]>('/my-lessons'),
  addMyLesson: (talk_id: string) => put<MyLesson[]>('/my-lessons', { talk_id }),
  removeMyLesson: (talk_id: string) => del<MyLesson[]>(`/my-lessons/${talk_id}`),
  reorderMyLessons: (talk_ids: string[]) => post<MyLesson[]>('/my-lessons/reorder', { talk_ids }),

  me: () => get<User>('/auth/me'),
  login: (email: string, password: string) => post<User>('/auth/login', { email, password }),
  logout: () => post<{ ok: boolean }>('/auth/logout'),
  setPassword: (token: string, password: string) => post<User>('/auth/set-password', { token, password }),
  forgot: (email: string) => post<{ ok: boolean }>('/auth/forgot', { email }),

  users: () => get<AdminUser[]>('/users'),
  inviteUser: (email: string, name: string, is_admin: boolean) =>
    post<{ user: User; emailed: boolean; link?: string; reason?: string }>('/users', { email, name, is_admin }),
  resendInvite: (id: number) => post<{ emailed: boolean; link?: string; reason?: string }>(`/users/${id}/invite`),
  patchUser: (id: number, body: { name?: string; is_admin?: boolean; disabled?: boolean }) =>
    patch<AdminUser[]>(`/users/${id}`, body),

  lessons: () =>
    get<{ talk: TalkSummary; updated_at: string; notes_len: number; pin_count: number; chat_count: number }[]>('/lessons'),
  lesson: (talkId: string) => get<Lesson>(`/lessons/${talkId}`),
  saveNotes: (talkId: string, notes_md: string) => put<Lesson>(`/lessons/${talkId}`, { notes_md }),
  addPin: (talkId: string, pin: Partial<Pin> & { kind: Pin['kind'] }) => post<Pin[]>(`/lessons/${talkId}/pins`, pin),
  patchPin: (talkId: string, pinId: number, body: { text?: string; note?: string }) =>
    patch<Pin[]>(`/lessons/${talkId}/pins/${pinId}`, body),
  deletePin: (talkId: string, pinId: number) => del<Pin[]>(`/lessons/${talkId}/pins/${pinId}`),
  reorderPins: (talkId: string, ids: number[]) => post<Pin[]>(`/lessons/${talkId}/pins/reorder`, { ids }),
  emailLesson: (talkId: string, to: string[], subject?: string) =>
    post<{ ok: boolean; to: string[]; subject: string }>(`/lessons/${talkId}/email`, { to, subject }),
  exportUrl: (talkId: string, sections?: string[]) =>
    `/api/lessons/${talkId}/export.html${sections?.length ? `?sections=${sections.join(',')}` : ''}`,

  aiStatus: () => get<{ configured: boolean; provider: string; label: string; email_ready: boolean; email_missing: string }>('/ai-status'),
  settings: () => get<Record<string, string | boolean>>('/settings'),
  saveSettings: (values: Record<string, string>) => put<Record<string, string | boolean>>('/settings', { values }),
  testAi: () => post<{ ok: boolean; provider: string; model: string; display_name?: string }>('/settings/test-ai'),
  ollamaModels: () => get<{ models: string[] }>('/settings/ollama/models'),
  testEmail: (to: string) => post<{ ok: boolean }>('/settings/test-email', { to }),

  indexStatus: () => get<IndexStatus>('/admin/index/status'),
  rebuildIndex: (skipEmbeddings = false) => post<IndexJob>(`/admin/index/rebuild?skip_embeddings=${skipEmbeddings}`),

  chatSessions: (talkId: string) => get<ChatSession[]>(`/chat/sessions?talk_id=${encodeURIComponent(talkId)}`),
  chatSession: (id: number) => get<ChatSession>(`/chat/sessions/${id}`),
  deleteSession: (id: number) => del<{ ok: boolean }>(`/chat/sessions/${id}`),
}

export interface IndexJob {
  running: boolean
  stage: string
  done: number
  total: number
  error: string | null
  started_at: string
  finished_at: string | null
  stats: Record<string, number> | null
}

export interface IndexStatus {
  ready: boolean
  built_at: string | null
  embedding_model: string | null
  stats: Record<string, number> | null
  talks_json_exists: boolean
  talks_json_mtime: string | null
  scriptures_json_exists: boolean
  embeddings_exist: boolean
  job: IndexJob | null
}

// ---- Server-sent events over fetch (POST body needed, so no EventSource)

export type SseHandler = (event: string, data: Record<string, any>) => void

export async function streamChat(
  body: { talk_id: string; message: string; session_id?: number | null },
  onEvent: SseHandler,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = 'message'
      const dataLines: string[] = []
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (dataLines.length) {
        try {
          onEvent(event, JSON.parse(dataLines.join('\n')))
        } catch {
          /* skip malformed */
        }
      }
    }
  }
}
