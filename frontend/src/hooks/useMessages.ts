import { useState, useEffect, useCallback, useRef } from 'react'
import type { Message } from '../types'
import { getMessages } from '../api/chats'

export function useMessages(contactKey: string | null) {
  const [messages, setMessages] = useState<Message[]>([])
  const prevKey = useRef<string | null>(null)

  const refresh = useCallback(async () => {
    if (!contactKey) return
    try {
      const data = await getMessages(contactKey)
      setMessages(data)
    } catch {
      // ignore
    }
  }, [contactKey])

  useEffect(() => {
    if (contactKey !== prevKey.current) {
      setMessages([])
      prevKey.current = contactKey
    }
    refresh()
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [contactKey, refresh])

  return { messages, refresh }
}
