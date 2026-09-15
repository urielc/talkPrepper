import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ gfm: true, breaks: true })

/**
 * Render Markdown to safe HTML. Citation tokens like [[talk:2024-10/15renlund]]
 * and [[scripture:Alma 41:14]] become <button data-cite=...> elements that the
 * host component wires up with a click handler.
 */
export function renderMarkdown(src: string): string {
  const withCites = src.replace(/\[\[(talk|scripture):([^\]]+)\]\]/g, (_m, kind: string, value: string) => {
    const v = value.trim()
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

/** Strip <mark> tags but keep their text (for plain-text copies). */
export function stripMarks(s: string): string {
  return s.replace(/<\/?mark>/g, '')
}
