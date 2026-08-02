import { useRef, useState } from 'react'

interface Props {
  label: string
  hint?: string
  accept: string
  disabled?: boolean
  done?: boolean
  /** Returns upload promise; progress is reported via the callback. */
  onFile: (file: File, onProgress: (fraction: number) => void) => Promise<void>
}

export function FileDrop({ label, hint, accept, disabled, done, onFile }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handle = async (file: File) => {
    setError(null)
    setProgress(0)
    try {
      await onFile(file, setProgress)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setProgress(null)
    }
  }

  const busy = progress !== null

  return (
    <div
      className={`file-drop ${dragOver ? 'file-drop--over' : ''} ${done ? 'file-drop--done' : ''} ${disabled ? 'file-drop--disabled' : ''}`}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled && !busy) setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        const file = e.dataTransfer.files[0]
        if (file && !disabled && !busy) void handle(file)
      }}
      onClick={() => {
        if (!disabled && !busy) inputRef.current?.click()
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handle(file)
          e.target.value = ''
        }}
      />
      <div className="file-drop-label">
        {done ? '✓ ' : ''}
        {label}
      </div>
      {hint ? <div className="file-drop-hint">{hint}</div> : null}
      {busy ? (
        <div className="file-drop-progress">
          <div className="file-drop-progress-bar" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
        </div>
      ) : null}
      {error ? <div className="file-drop-error">{error}</div> : null}
    </div>
  )
}
