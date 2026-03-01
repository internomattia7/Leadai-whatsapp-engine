import { useEffect, useRef, useState } from 'react'
import { MessageSquare, ArrowLeft, Phone } from 'lucide-react'
import MessageBubble from './MessageBubble'
import MessageInput from './MessageInput'
import Avatar from '../ui/Avatar'
import { useMessages } from '../../hooks/useMessages'
import type { Chat, Message } from '../../types'
import { sendMessage, sendMedia, markRead } from '../../api/chats'

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

  // When server messages update, remove any optimistic message that is now
  // covered by a real server message (matched by body + direction + time window).
  // This prevents the message from ever disappearing during a refresh race condition:
  // the optimistic stays visible until the server actually confirms it.
  useEffect(() => {
    setOptimisticMsgs(prev => {
      if (prev.length === 0) return prev
      return prev.filter(opt => {
        // Always keep error messages visible so user sees the failure
        if (opt.status === 'error') return true
        const optTime = new Date(opt.ts || 0).getTime()
        // Remove only if a matching real message appeared in server data
        const matched = messages.some(
          m =>
            m.direction === 'out' &&
            m.body === opt.body &&
            Math.abs(new Date(m.ts || 0).getTime() - optTime) < 30_000
        )
        return !matched
      })
    })
  }, [messages]) // eslint-disable-line react-hooks/exhaustive-deps

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
      msg_type: 'text',
    }

    // Show bubble immediately
    setOptimisticMsgs(prev => [...prev, tempMsg])

    try {
      await sendMessage(chat.contact_key, text)
      // Update to 'sent' while waiting for server to confirm via polling/refresh
      setOptimisticMsgs(prev =>
        prev.map(m => m.id === tempId ? { ...m, status: 'sent' } : m)
      )
      // Trigger a background refresh — when it returns, the useEffect above
      // will automatically remove the optimistic message once matched
      refresh()
    } catch {
      setOptimisticMsgs(prev =>
        prev.map(m => m.id === tempId ? { ...m, status: 'error' } : m)
      )
    }
  }

  const handleSendMedia = async (file: File) => {
    const tempId = `tmp-media-${Date.now()}`
    const isImage = file.type.startsWith('image/')
    const waType = isImage ? 'image'
                 : file.type.startsWith('video/') ? 'video'
                 : file.type.startsWith('audio/') ? 'audio'
                 : 'document'

    // Optimistic preview: show local object URL for images
    const localUrl = isImage ? URL.createObjectURL(file) : null
    const tempMsg: Message = {
      id: tempId,
      direction: 'out',
      body: file.name,
      ts: new Date().toISOString(),
      status: 'pending',
      msg_type: waType as Message['msg_type'],
      media_url: localUrl,
      mime_type: file.type,
      filename: file.name,
    }

    setOptimisticMsgs(prev => [...prev, tempMsg])

    try {
      await sendMedia(chat.contact_key, file)
      setOptimisticMsgs(prev =>
        prev.map(m => m.id === tempId ? { ...m, status: 'sent' } : m)
      )
      refresh()
    } catch {
      setOptimisticMsgs(prev =>
        prev.map(m => m.id === tempId ? { ...m, status: 'error' } : m)
      )
    } finally {
      if (localUrl) URL.revokeObjectURL(localUrl)
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

        {/* Call button */}
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
      <MessageInput onSend={handleSend} onSendMedia={handleSendMedia} />
    </div>
  )
}
