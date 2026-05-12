import { Fragment, type ReactNode } from 'react'

interface SimpleMarkdownProps {
  content: string
  className?: string
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index))
    }
    const token = match[0]
    if (token.startsWith('**') && token.endsWith('**')) {
      nodes.push(
        <strong key={`${match.index}-bold`} className="font-semibold text-slate-950">
          {token.slice(2, -2)}
        </strong>,
      )
    } else if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(
        <code
          key={`${match.index}-code`}
          className="rounded bg-slate-900/6 px-1 py-0.5 font-mono text-[0.92em] text-slate-800"
        >
          {token.slice(1, -1)}
        </code>,
      )
    } else {
      nodes.push(token)
    }
    cursor = match.index + token.length
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor))
  }

  return nodes
}

function renderParagraphLines(text: string) {
  return text.split('\n').map((line, index) => (
    <Fragment key={`line-${index}`}>
      {index > 0 ? <br /> : null}
      {renderInline(line)}
    </Fragment>
  ))
}

export function stripMarkdown(content: string) {
  return content
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^[-*]\s+/gm, '')
    .replace(/^\d+\.\s+/gm, '')
    .trim()
}

export default function SimpleMarkdown({ content, className }: SimpleMarkdownProps) {
  const blocks = content
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean)

  return (
    <div className={className}>
      {blocks.map((block, index) => {
        if (block.startsWith('### ')) {
          return (
            <h3 key={`h3-${index}`} className="mb-2 text-base font-semibold text-slate-950">
              {renderInline(block.slice(4))}
            </h3>
          )
        }

        if (block.startsWith('## ')) {
          return (
            <h2 key={`h2-${index}`} className="mb-2 text-lg font-semibold text-slate-950">
              {renderInline(block.slice(3))}
            </h2>
          )
        }

        if (block.startsWith('# ')) {
          return (
            <h1 key={`h1-${index}`} className="mb-2 text-xl font-semibold text-slate-950">
              {renderInline(block.slice(2))}
            </h1>
          )
        }

        const listLines = block
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)

        const isBlockquote = listLines.every((line) => line.startsWith('>'))
        if (isBlockquote) {
          return (
            <blockquote
              key={`quote-${index}`}
              className="mb-3 border-l-2 border-cyan-300/80 bg-cyan-50/60 px-3 py-2 text-sm leading-relaxed text-slate-700 italic"
            >
              {listLines.map((line, lineIndex) => (
                <Fragment key={`quote-line-${lineIndex}`}>
                  {lineIndex > 0 ? <br /> : null}
                  {renderInline(line.replace(/^>\s?/, ''))}
                </Fragment>
              ))}
            </blockquote>
          )
        }

        const isBulletList = listLines.every((line) => /^[-*]\s+/.test(line))
        if (isBulletList) {
          return (
            <ul key={`ul-${index}`} className="mb-3 list-disc space-y-1 pl-5 marker:text-cyan-700">
              {listLines.map((line, lineIndex) => (
                <li key={`li-${lineIndex}`} className="text-sm leading-relaxed text-inherit">
                  {renderInline(line.replace(/^[-*]\s+/, ''))}
                </li>
              ))}
            </ul>
          )
        }

        const isOrderedList = listLines.every((line) => /^\d+\.\s+/.test(line))
        if (isOrderedList) {
          return (
            <ol key={`ol-${index}`} className="mb-3 list-decimal space-y-1 pl-5 marker:text-cyan-700">
              {listLines.map((line, lineIndex) => (
                <li key={`oli-${lineIndex}`} className="text-sm leading-relaxed text-inherit">
                  {renderInline(line.replace(/^\d+\.\s+/, ''))}
                </li>
              ))}
            </ol>
          )
        }

        return (
          <p key={`p-${index}`} className="mb-3 text-sm leading-relaxed text-inherit last:mb-0">
            {renderParagraphLines(block)}
          </p>
        )
      })}
    </div>
  )
}
