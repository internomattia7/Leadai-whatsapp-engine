import { Check, Clock, AlertCircle } from 'lucide-react'
import type { Message } from '../../types'

interface MessageBubbleProps {
  message: Message
}

function formatTs(ts: string | null) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'sent' || status === 'read') return <Check size={12} className="text-cyan" />
  if (status === 'queued' || status === 'pending') return <Clock size={12} className="text-muted opacity-60" />
  if (status === 'error' || status === 'failed') return <AlertCircle size={12} className="text-red-400" />
  return null
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
        <p className="leading-relaxed whitespace-pre-wrap">{message.body}</p>
        <div className={`flex items-center gap-1 mt-1 ${isOut ? 'justify-end' : 'justify-start'}`}>
          <span className="text-xs opacity-60">{formatTs(message.ts)}</span>
          {isOut && <StatusIcon status={message.status} />}
        </div>
      </div>
    </div>
  )
}
