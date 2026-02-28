import { useEffect, useRef } from 'react'
import { MessageSquare, ArrowLeft } from 'lucide-react'
import MessageBubble from './MessageBubble'
import MessageInput from './MessageInput'
import Avatar from '../ui/Avatar'
import { useMessages } from '../../hooks/useMessages'
import type { Chat } from '../../types'
import { sendMessage, markRead } from '../../api/chats'

interface ChatWindowProps {
  chat: Chat | null
  onBack?: () => void
}

export default function ChatWindow({ chat, onBack }: ChatWindowProps) {
  const { messages, refresh } = useMessages(chat?.contact_key ?? null)
  const bottomRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  // Mark read when chat opens
  useEffect(() => {
    if (chat?.contact_key) {
      markRead(chat.contact_key).catch(() => {})
    }
  }, [chat?.contact_key])

  if (!chat) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-muted">
        <MessageSquare size={40} />
        <span className="text-sm">Seleziona una chat per iniziare</span>
      </div>
    )
  }

  const handleSend = async (text: string) => {
    try {
      await sendMessage(chat.contact_key, text)
      refresh()
    } catch {
      // ignore
    }
  }

  return (
    <div className="flex flex-col h-full bg-bg">
      {/* Chat header */}
      <div className="px-4 py-3 border-b border-border bg-surface flex items-center gap-3">
        {onBack && (
          <button
            onClick={onBack}
            className="md:hidden -ml-1 mr-1 p-1 text-muted hover:text-text transition-colors"
            aria-label="Torna alla lista"
          >
            <ArrowLeft size={20} />
          </button>
        )}
        <Avatar
          name={chat.nome_cliente || chat.telefono || '?'}
          imageUrl={chat.profile_image_url}
          size="md"
        />
        <div className="min-w-0">
          <div className="text-sm font-semibold truncate">
            {chat.nome_cliente || chat.telefono || chat.contact_key}
          </div>
          {chat.telefono && (
            <div className="text-xs text-muted">{chat.telefono}</div>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <div className="text-center text-muted text-sm mt-8">Nessun messaggio ancora</div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={`${msg.direction}-${msg.id}-${i}`} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <MessageInput onSend={handleSend} />
    </div>
  )
}
