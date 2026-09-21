import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

/** What the server found when it checked one citation against the library. */
export interface CitationCheck {
  ok: boolean
  label?: string | null
}

/**
 * Render Markdown to safe HTML. Citation tokens like [[talk:2024-10/15renlund]]
 * and [[scripture:Alma 41:14]] become <button data-cite=...> elements that the
 * host component wires up with a click handler.
 *
 * `citations` is the server's verdict per token, keyed "kind:value". One marked
 * `ok: false` names nothing in the library, so it renders as plain marked text
 * rather than a link — there is nothing for a click to open. A token the map
 * says nothing about keeps its link, which is what messages stored before the
 * check existed rely on.
 */
export function renderMarkdown(src: string, citations?: Record<string, CitationCheck>): string {
  const withCites = src.replace(/\[\[(talk|scripture):([^\]]+)\]\]/g, (_m, kind: string, value: string) => {
    const v = value.trim()
    if (citations?.[`${kind}:${v}`]?.ok === false) {
      return `<span class="cite cite-bad" title="Not found in the library">${escapeHtml(v)}</span>`
    }
    const label = kind === 'talk' ? 'open talk' : v
    return `<button type="button" class="cite cite-${kind}" data-cite-kind="${kind}" data-cite-value="${escapeAttr(v)}">${escapeHtml(label)}</button>`
  })
  const html = marked.parse(withCites) as string
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ['button'],
    ADD_ATTR: ['data-cite-kind', 'data-cite-value', 'type'],
  })
}

export function renderInline(src: string): string {
  return DOMPurify.sanitize(marked.parseInline(src) as string)
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function escapeAttr(s: string): string {
  return escapeHtml(s).replace(/"/g, '&quot;')
}

/** Search snippets come from SQLite's highlighter as HTML with <mark> tags; allow nothing else. */
export function safeSnippet(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS: ['mark'], ALLOWED_ATTR: [] })
}

/** Strip <mark> tags but keep their text (for plain-text copies). */
export function stripMarks(s: string): string {
  return s.replace(/<\/?mark>/g, '')
}
