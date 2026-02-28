import { useState } from 'react'
import { Search, MessageSquare } from 'lucide-react'
import type { Chat } from '../../types'

type Tab = 'all' | 'new' | 'follow' | 'closed'

const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'Tutti' },
  { key: 'new', label: 'Nuovi' },
  { key: 'follow', label: 'Da seguire' },
  { key: 'closed', label: 'Chiusi' },
]

function faseToTab(fase: string | null): Tab {
  if (!fase || fase === 'nuovo') return 'new'
  if (fase === 'chiuso' || fase === 'inviato') return 'closed'
  return 'follow'
}

function formatTime(ts: string | null) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86400000) return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit' })
}

interface SidebarProps {
  chats: Chat[]
  selectedKey: string | null
  onSelect: (key: string) => void
}

export default function Sidebar({ chats, selectedKey, onSelect }: SidebarProps) {
  const [tab, setTab] = useState<Tab>('all')
  const [search, setSearch] = useState('')

  const filtered = chats.filter(c => {
    if (tab !== 'all' && faseToTab(c.fase_preventivo) !== tab) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        (c.nome_cliente || '').toLowerCase().includes(q) ||
        (c.telefono || '').includes(q)
      )
    }
    return true
  })

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <img src="/icons/logo.svg" className="w-7 h-7" alt="VenomApp" />
        <span className="font-semibold text-sm tracking-wide text-violet">VenomApp</span>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2 bg-card rounded-lg px-3 py-1.5">
          <Search size={14} className="text-muted" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Cerca contatto..."
            className="bg-transparent text-sm text-text placeholder-muted flex-1"
          />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 text-xs py-2 transition-colors ${
              tab === t.key
                ? 'text-violet border-b-2 border-violet font-medium'
                : 'text-muted hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Chat list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center h-32 text-muted text-sm gap-2">
            <MessageSquare size={24} />
            <span>Nessuna chat</span>
          </div>
        )}
        {filtered.map(chat => (
          <button
            key={chat.contact_key}
            onClick={() => onSelect(chat.contact_key)}
            className={`w-full text-left px-4 py-3 border-b border-border transition-colors flex gap-3 items-start ${
              selectedKey === chat.contact_key
                ? 'bg-violet/10 border-l-2 border-l-violet'
                : 'hover:bg-card'
            }`}
          >
            {/* Avatar */}
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-violet to-cyan flex-shrink-0 flex items-center justify-center text-sm font-bold text-white">
              {(chat.nome_cliente || chat.telefono || '?')[0].toUpperCase()}
            </div>
            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-1">
                <span className="text-sm font-medium truncate">
                  {chat.nome_cliente || chat.telefono || chat.contact_key}
                </span>
                <span className="text-xs text-muted flex-shrink-0">{formatTime(chat.last_at)}</span>
              </div>
              <div className="flex items-center justify-between gap-1 mt-0.5">
                <span className="text-xs text-muted truncate">
                  {chat.last_message || '—'}
                </span>
                {chat.unread_count > 0 && (
                  <span className="ml-1 flex-shrink-0 bg-violet text-white text-xs rounded-full w-5 h-5 flex items-center justify-center font-bold">
                    {chat.unread_count > 9 ? '9+' : chat.unread_count}
                  </span>
                )}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
