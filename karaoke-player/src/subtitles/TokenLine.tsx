import { forwardRef, Fragment } from 'react'
import type { SubtitleLine } from '../api/types'

interface Props {
  line: SubtitleLine
  variant: 'current' | 'next'
}

// Hiragana, Katakana (incl. halfwidth), and CJK ideographs. Tokens for these
// scripts are per-character and must butt together with no separator; latin /
// space-delimited scripts get a space between words.
const CJK = /[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]/

/** A space goes between two tokens only when neither side is CJK. */
function spaceBetween(prev: string, next: string): boolean {
  if (!prev || !next) return false
  return !CJK.test(prev[prev.length - 1]) && !CJK.test(next[0])
}

function tokenContent(text: string, ruby?: string | null) {
  if (ruby) {
    return (
      <ruby>
        {text}
        <rt>{ruby}</rt>
      </ruby>
    )
  }
  return text
}

/**
 * One lyric line. Each token has a base layer and a fill layer clipped by the
 * CSS var --fill (0–100%), which SubtitleOverlay drives per animation frame —
 * no React re-render on the hot path.
 */
export const TokenLine = forwardRef<HTMLDivElement, Props>(function TokenLine(
  { line, variant },
  ref,
) {
  return (
    <div className={`subtitle-line subtitle-line--${variant}`} ref={ref}>
      {line.tokens.map((tok, i) => (
        <Fragment key={i}>
          {i > 0 && spaceBetween(line.tokens[i - 1].text, tok.text) ? ' ' : null}
          <span className="tok" style={{ ['--fill' as string]: '0%' }}>
            <span className="tok-base">{tokenContent(tok.text, tok.ruby)}</span>
            <span className="tok-fill" aria-hidden>
              {tokenContent(tok.text, tok.ruby)}
            </span>
          </span>
        </Fragment>
      ))}
      {line.translation ? <div className="subtitle-translation">{line.translation}</div> : null}
    </div>
  )
})
