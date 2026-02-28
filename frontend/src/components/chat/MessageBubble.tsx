import { Check, CheckCheck, Clock } from 'lucide-react'
import type { Message } from '../../types'

interface MessageBubbleProps {
  message: Message
}

function formatTs(ts: string | null) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

function StatusIcon({ status }: { status: string }) {
  // ⏳ pending/queued/sent → waiting for delivery receipt
  if (status === 'pending' || status === 'queued' || status === 'sent') {
    return <Clock size={12} className="text-white/50" />
  }
  // ✓✓ green → read
  if (status === 'read') {
    return <CheckCheck size={12} className="text-green-400" />
  }
  // ✓✓ gray → delivered
  if (status === 'delivered') {
    return <CheckCheck size={12} className="text-white/60" />
  }
  // ✓ red → error (not sent)
  if (status === 'error' || status === 'failed') {
    return <Check size={12} className="text-red-400" />
  }
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
