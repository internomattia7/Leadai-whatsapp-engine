import { useRef, useState } from 'react'
import { Send, Paperclip } from 'lucide-react'

interface MessageInputProps {
  onSend: (text: string) => void
  onSendMedia?: (file: File) => void
  disabled?: boolean
}

const ACCEPTED = 'image/jpeg,image/png,image/webp,image/gif,video/mp4,audio/ogg,audio/mpeg,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

export default function MessageInput({ onSend, onSendMedia, disabled }: MessageInputProps) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !onSendMedia) return
    onSendMedia(file)
    // reset so the same file can be re-sent
    e.target.value = ''
  }

  return (
    <div className="border-t border-border bg-surface px-4 pt-3 pb-3 flex items-end gap-3" style={{ paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom, 0px))' }}>
      <button
        className="text-muted hover:text-text transition-colors mb-1"
        title="Allega file"
        onClick={() => fileRef.current?.click()}
        disabled={disabled}
        type="button"
      >
        <Paperclip size={18} />
      </button>
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPTED}
        className="hidden"
        onChange={handleFileChange}
      />

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
        type="button"
      >
        <Send size={16} className="text-white" />
      </button>
    </div>
  )
}
