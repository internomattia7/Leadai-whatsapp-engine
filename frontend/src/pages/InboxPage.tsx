import { useState } from 'react'
import AppShell from '../components/layout/AppShell'
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
  const { chats } = useChats()
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const selectedChat: Chat | null = chats.find(c => c.contact_key === selectedKey) ?? null

  return (
    <div className="flex flex-col h-screen">
      <InstallBanner />
      <div className="flex-1 overflow-hidden">
        <AppShell
          sidebar={
            <Sidebar
              chats={chats}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
            />
          }
          main={<ChatWindow chat={selectedChat} />}
          panel={<LeadPanel chat={selectedChat} currentUser={currentUser} />}
        />
      </div>
    </div>
  )
}
