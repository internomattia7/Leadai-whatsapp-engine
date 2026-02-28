import { useState, useEffect } from 'react'
import { Phone, Hash, Tag, User as UserIcon, Pencil, Check, X } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Chat, User as UserType } from '../../types'
import { updateContactName } from '../../api/chats'
import Avatar from '../ui/Avatar'

interface LeadPanelProps {
  chat: Chat | null
  currentUser: UserType | null
  onContactUpdated?: () => void
}

const FASE_COLORS: Record<string, string> = {
  nuovo: 'bg-cyan/20 text-cyan',
  in_preparazione: 'bg-yellow-500/20 text-yellow-400',
  inviato: 'bg-violet/20 text-violet',
  chiuso: 'bg-green-500/20 text-green-400',
}

const ESITO_COLORS: Record<string, string> = {
  positivo: 'bg-green-500/20 text-green-400',
  negativo: 'bg-red-500/20 text-red-400',
  in_attesa: 'bg-yellow-500/20 text-yellow-400',
}

export default function LeadPanel({ chat, currentUser, onContactUpdated }: LeadPanelProps) {
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [saving, setSaving] = useState(false)

  // Sync name input when chat changes
  useEffect(() => {
    setNameInput(chat?.nome_cliente || '')
    setEditingName(false)
  }, [chat?.contact_key])

  if (!chat) {
    return (
      <div className="flex items-center justify-center h-full bg-surface text-muted text-sm">
        Seleziona una chat
      </div>
    )
  }

  const displayName = chat.nome_cliente || chat.telefono || chat.contact_key
  const businessPhone = currentUser?.business_phone

  const handleSaveName = async () => {
    if (!nameInput.trim()) return
    setSaving(true)
    try {
      await updateContactName(chat.contact_key, nameInput.trim())
      setEditingName(false)
      onContactUpdated?.()
    } catch {
      // ignore
    } finally {
      setSaving(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSaveName()
    if (e.key === 'Escape') { setEditingName(false); setNameInput(chat.nome_cliente || '') }
  }

  return (
    <div className="flex flex-col h-full bg-surface p-4 gap-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-text/70 uppercase tracking-wider">Dettagli Lead</h2>

      {/* Avatar + editable name */}
      <div className="flex flex-col items-center gap-2 py-3">
        <Avatar
          name={displayName}
          imageUrl={chat.profile_image_url}
          size="lg"
        />

        {editingName ? (
          <div className="flex items-center gap-1 w-full px-2">
            <input
              autoFocus
              value={nameInput}
              onChange={e => setNameInput(e.target.value)}
              onKeyDown={handleKeyDown}
              className="flex-1 bg-card border border-violet rounded-lg px-2 py-1 text-sm text-text text-center"
              placeholder="Nome contatto"
            />
            <button
              onClick={handleSaveName}
              disabled={saving}
              className="text-cyan hover:text-cyan/80 disabled:opacity-40"
              title="Salva"
            >
              <Check size={15} />
            </button>
            <button
              onClick={() => { setEditingName(false); setNameInput(chat.nome_cliente || '') }}
              className="text-muted hover:text-text"
              title="Annulla"
            >
              <X size={15} />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 group">
            <span className="text-base font-semibold text-text">{displayName}</span>
            <button
              onClick={() => { setNameInput(chat.nome_cliente || ''); setEditingName(true) }}
              className="text-muted opacity-0 group-hover:opacity-100 transition-opacity hover:text-violet"
              title="Modifica nome"
            >
              <Pencil size={13} />
            </button>
          </div>
        )}

        {chat.telefono && (
          <span className="text-xs text-muted">{chat.telefono}</span>
        )}
      </div>

      {/* Fields */}
      <div className="space-y-3">
        <Row icon={<Hash size={14} />} label="Contact Key" value={chat.contact_key} mono />
        <Row icon={<UserIcon size={14} />} label="Nome" value={chat.nome_cliente || '—'} />
        <Row icon={<Phone size={14} />} label="Telefono" value={chat.telefono || '—'} />
      </div>

      {/* Status badges */}
      <div className="space-y-2">
        {chat.fase_preventivo && (
          <div className="flex items-center gap-2">
            <Tag size={13} className="text-muted" />
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${FASE_COLORS[chat.fase_preventivo] || 'bg-muted/20 text-muted'}`}>
              {chat.fase_preventivo.replace(/_/g, ' ')}
            </span>
          </div>
        )}
        {chat.esito_cliente && (
          <div className="flex items-center gap-2">
            <Tag size={13} className="text-muted" />
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ESITO_COLORS[chat.esito_cliente] || 'bg-muted/20 text-muted'}`}>
              {chat.esito_cliente.replace(/_/g, ' ')}
            </span>
          </div>
        )}
      </div>

      {/* Chiama Ora */}
      {businessPhone ? (
        <a
          href={`tel:${businessPhone}`}
          className="mt-auto flex items-center justify-center gap-2 bg-gradient-to-r from-violet to-cyan text-white text-sm font-semibold py-2.5 rounded-xl hover:opacity-90 transition-opacity"
        >
          <Phone size={16} />
          Chiama Ora
        </a>
      ) : (
        <div className="mt-auto text-xs text-muted text-center">
          Imposta il tuo numero in Impostazioni per usare "Chiama Ora"
        </div>
      )}
    </div>
  )
}

function Row({ icon, label, value, mono }: { icon: ReactNode; label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-muted mt-0.5">{icon}</span>
      <div className="min-w-0">
        <div className="text-xs text-muted">{label}</div>
        <div className={`text-sm text-text truncate ${mono ? 'font-mono text-xs' : ''}`}>{value}</div>
      </div>
    </div>
  )
}
