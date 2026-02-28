import { useState } from 'react'
import Sidebar from '../components/layout/Sidebar'
import ChatWindow from '../components/chat/ChatWindow'
import LeadPanel from '../components/layout/LeadPanel'
import InstallBanner from '../components/pwa/InstallBanner'
import { useChats } from '../hooks/useChats'
import type { User, Chat } from '../types'

interface InboxPageProps {
  currentUser: User | null
}

export default function InboxPage({ currentUser }: InboxPageProps) {
  const { chats, refresh } = useChats()
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const selectedChat: Chat | null = chats.find(c => c.contact_key === selectedKey) ?? null

  const handleSelect = (key: string) => setSelectedKey(key)
  const handleBack = () => setSelectedKey(null)

  return (
    <div className="flex flex-col h-screen h-dvh bg-bg text-text">
      <InstallBanner />

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Sidebar
            - Mobile: full width, visible only when no chat is selected
            - Desktop: fixed 320px column, always visible */}
        <div className={`
          flex-shrink-0 border-r border-border overflow-hidden flex flex-col
          ${selectedKey ? 'hidden' : 'flex w-full'}
          md:flex md:w-80
        `}>
          <Sidebar chats={chats} selectedKey={selectedKey} onSelect={handleSelect} />
        </div>

        {/* Chat window
            - Mobile: full width, visible only when a chat is selected
            - Desktop: flex-1, always visible */}
        <div className={`
          overflow-hidden flex-col min-w-0
          ${selectedKey ? 'flex w-full' : 'hidden'}
          md:flex md:flex-1
        `}>
          <ChatWindow chat={selectedChat} onBack={handleBack} />
        </div>

        {/* Lead panel: hidden on mobile, 288px on desktop */}
        <div className="hidden md:flex md:w-72 flex-shrink-0 border-l border-border overflow-hidden flex-col">
          <LeadPanel chat={selectedChat} currentUser={currentUser} onContactUpdated={refresh} />
        </div>
      </div>
    </div>
  )
}
