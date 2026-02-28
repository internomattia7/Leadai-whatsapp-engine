import { useEffect, useRef, useState } from 'react'
import { MessageSquare, ArrowLeft, Phone } from 'lucide-react'
import MessageBubble from './MessageBubble'
import MessageInput from './MessageInput'
import Avatar from '../ui/Avatar'
import { useMessages } from '../../hooks/useMessages'
import type { Chat, Message } from '../../types'
import { sendMessage, markRead } from '../../api/chats'

interface ChatWindowProps {
  chat: Chat | null
  onBack?: () => void
}

export default function ChatWindow({ chat, onBack }: ChatWindowProps) {
  const { messages, refresh } = useMessages(chat?.contact_key ?? null)
  const [optimisticMsgs, setOptimisticMsgs] = useState<Message[]>([])
  const bottomRef = useRef<HTMLDivElement>(null)

  const allMessages = [...messages, ...optimisticMsgs]

  // Scroll to bottom on new messages (including optimistic)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [allMessages.length])

  // Mark read when chat opens
  useEffect(() => {
    if (chat?.contact_key) {
      markRead(chat.contact_key).catch(() => {})
    }
  }, [chat?.contact_key])

  // Clear optimistic messages when switching chat
  useEffect(() => {
    setOptimisticMsgs([])
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
    const tempId = `tmp-${Date.now()}`
    const tempMsg: Message = {
      id: tempId,
      direction: 'out',
      body: text,
      ts: new Date().toISOString(),
      status: 'pending',
    }

    // A) Optimistic: show bubble immediately
    setOptimisticMsgs(prev => [...prev, tempMsg])

    try {
      await sendMessage(chat.contact_key, text)
      // B+C) Fetch real messages from server, then drop the optimistic bubble
      await refresh()
      setOptimisticMsgs(prev => prev.filter(m => m.id !== tempId))
    } catch {
      // Mark the bubble as error so user knows it failed
      setOptimisticMsgs(prev =>
        prev.map(m => m.id === tempId ? { ...m, status: 'error' } : m)
      )
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
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold truncate">
            {chat.nome_cliente || chat.telefono || chat.contact_key}
          </div>
          {chat.telefono && (
            <div className="text-xs text-muted">{chat.telefono}</div>
          )}
        </div>

        {/* FIX #1 — Call button */}
        {chat.telefono && (
          <a
            href={`tel:${chat.telefono}`}
            className="flex-shrink-0 w-11 h-11 flex items-center justify-center rounded-full bg-card hover:bg-border text-muted hover:text-cyan transition-colors"
            aria-label={`Chiama ${chat.telefono}`}
            title={`Chiama ${chat.telefono}`}
          >
            <Phone size={18} />
          </a>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3">
        {allMessages.length === 0 && (
          <div className="text-center text-muted text-sm mt-8">Nessun messaggio ancora</div>
        )}
        {allMessages.map((msg, i) => (
          <MessageBubble key={`${msg.direction}-${msg.id}-${i}`} message={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <MessageInput onSend={handleSend} />
    </div>
  )
}
