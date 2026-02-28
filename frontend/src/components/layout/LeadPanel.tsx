import { Phone, Hash, Tag, User as UserIcon } from 'lucide-react'
import type { Chat, User as UserType } from '../../types'

interface LeadPanelProps {
  chat: Chat | null
  currentUser: UserType | null
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

export default function LeadPanel({ chat, currentUser }: LeadPanelProps) {
  if (!chat) {
    return (
      <div className="flex items-center justify-center h-full bg-surface text-muted text-sm">
        Seleziona una chat
      </div>
    )
  }

  const businessPhone = currentUser?.business_phone

  return (
    <div className="flex flex-col h-full bg-surface p-4 gap-4 overflow-y-auto">
      <h2 className="text-sm font-semibold text-text/70 uppercase tracking-wider">Dettagli Lead</h2>

      {/* Avatar + name */}
      <div className="flex flex-col items-center gap-2 py-3">
        <div className="w-14 h-14 rounded-full bg-gradient-to-br from-violet to-cyan flex items-center justify-center text-2xl font-bold text-white">
          {(chat.nome_cliente || chat.telefono || '?')[0].toUpperCase()}
        </div>
        <span className="text-base font-semibold text-text">
          {chat.nome_cliente || chat.telefono || chat.contact_key}
        </span>
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

import type { ReactNode } from 'react'
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
