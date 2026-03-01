import { useState } from 'react'
import { Check, CheckCheck, Clock, FileText, Download, X } from 'lucide-react'
import type { Message } from '../../types'

interface MessageBubbleProps {
  message: Message
}

function formatTs(ts: string | null) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'pending' || status === 'queued' || status === 'sent') {
    return <Clock size={12} className="text-white/50" />
  }
  if (status === 'read') {
    return <CheckCheck size={12} className="text-green-400" />
  }
  if (status === 'delivered') {
    return <CheckCheck size={12} className="text-white/60" />
  }
  if (status === 'error' || status === 'failed') {
    return <Check size={12} className="text-red-400" />
  }
  return null
}

/** Full-screen lightbox for images — stays inside the PWA, no new tab */
function ImageLightbox({ src, onClose }: { src: string; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
      onClick={onClose}
    >
      <button
        className="absolute top-4 right-4 text-white/80 hover:text-white"
        onClick={onClose}
        aria-label="Chiudi"
      >
        <X size={28} />
      </button>
      <img
        src={src}
        alt="immagine"
        className="max-w-full max-h-full object-contain"
        onClick={e => e.stopPropagation()}
      />
    </div>
  )
}

function MediaContent({ message }: { message: Message }) {
  const { msg_type, media_url, filename, body } = message
  const [lightbox, setLightbox] = useState(false)

  if (msg_type === 'image' && media_url) {
    return (
      <>
        {lightbox && <ImageLightbox src={media_url} onClose={() => setLightbox(false)} />}
        <div className="mb-1">
          <img
            src={media_url}
            alt={filename || 'immagine'}
            className="rounded-xl max-w-full max-h-60 object-cover cursor-pointer"
            onClick={() => setLightbox(true)}
            loading="lazy"
          />
          {body && body !== '[image]' && (
            <p className="leading-relaxed whitespace-pre-wrap mt-1 text-sm">{body}</p>
          )}
        </div>
      </>
    )
  }

  if (msg_type === 'document') {
    const name = filename || body || 'documento'
    return (
      <div className="mb-1">
        <a
          href={media_url || '#'}
          download={filename || undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 bg-black/20 rounded-lg px-3 py-2 hover:bg-black/30 transition-colors"
        >
          <FileText size={20} className="flex-shrink-0 text-cyan" />
          <span className="text-sm truncate flex-1">{name}</span>
          {media_url && <Download size={14} className="flex-shrink-0 opacity-70" />}
        </a>
      </div>
    )
  }

  if (msg_type === 'audio') {
    return (
      <div className="mb-1">
        {media_url
          ? <audio controls src={media_url} className="max-w-full" />
          : <p className="text-sm opacity-60 italic">🎵 {body || 'messaggio audio'}</p>
        }
      </div>
    )
  }

  if (msg_type === 'video' && media_url) {
    return (
      <div className="mb-1">
        <video controls src={media_url} className="rounded-xl max-w-full max-h-60" />
        {body && body !== '[video]' && (
          <p className="leading-relaxed whitespace-pre-wrap mt-1 text-sm">{body}</p>
        )}
      </div>
    )
  }

  // Pending outbound media (optimistic): show placeholder
  if (msg_type && msg_type !== 'text' && !media_url) {
    const t = msg_type as string
    const icon = t === 'image' ? '🖼️'
               : t === 'document' ? '📄'
               : t === 'audio' ? '🎵'
               : '🎥'
    const label = filename || body || `[${msg_type}]`
    return (
      <p className="text-sm opacity-60 italic mb-1">{icon} {label}</p>
    )
  }

  // Plain text fallback
  return <p className="leading-relaxed whitespace-pre-wrap">{body}</p>
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isOut = message.direction === 'out'

  return (
    <div className={`flex ${isOut ? 'justify-end' : 'justify-start'} mb-1`}>
      <div
        className={`max-w-[70%] px-3 py-2 rounded-2xl text-sm break-words ${
          isOut
            ? 'bg-violet text-white rounded-br-sm'
            : 'bg-surface text-text rounded-bl-sm'
        }`}
      >
        <MediaContent message={message} />
        <div className={`flex items-center gap-1 mt-1 ${isOut ? 'justify-end' : 'justify-start'}`}>
          <span className="text-xs opacity-60">{formatTs(message.ts)}</span>
          {isOut && <StatusIcon status={message.status} />}
        </div>
      </div>
    </div>
  )
}
