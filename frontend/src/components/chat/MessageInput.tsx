import { useRef, useState } from 'react'
import { Send, Paperclip } from 'lucide-react'

interface MessageInputProps {
  onSend: (text: string) => void
  disabled?: boolean
}

export default function MessageInput({ onSend, disabled }: MessageInputProps) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const submit = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText('')
    if (ref.current) {
      ref.current.style.height = 'auto'
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    if (ref.current) {
      ref.current.style.height = 'auto'
      ref.current.style.height = ref.current.scrollHeight + 'px'
    }
  }

  return (
    <div className="border-t border-border bg-surface px-4 py-3 flex items-end gap-3">
      <button
        className="text-muted hover:text-text transition-colors mb-1"
        title="Allega file"
        onClick={() => document.getElementById('va-file-input')?.click()}
      >
        <Paperclip size={18} />
      </button>
      <input id="va-file-input" type="file" className="hidden" />

      <textarea
        ref={ref}
        value={text}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder="Scrivi un messaggio..."
        rows={1}
        disabled={disabled}
        className="flex-1 bg-card text-text text-sm placeholder-muted rounded-xl px-4 py-2.5 resize-none max-h-32 border border-border focus:border-violet transition-colors"
        style={{ overflow: 'hidden' }}
      />

      <button
        onClick={submit}
        disabled={disabled || !text.trim()}
        className="mb-1 w-9 h-9 rounded-full bg-violet flex items-center justify-center disabled:opacity-40 hover:bg-violet/80 transition-colors"
      >
        <Send size={16} className="text-white" />
      </button>
    </div>
  )
}
