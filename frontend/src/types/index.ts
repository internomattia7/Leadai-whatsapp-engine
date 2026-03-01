export interface User {
  user_id: string
  email: string
  role: string
  azienda_id: string
  azienda_nome: string
  business_phone: string | null
}

export interface Chat {
  id: number
  contact_key: string
  nome_cliente: string | null
  telefono: string | null
  profile_image_url: string | null
  fase_preventivo: string | null
  esito_cliente: string | null
  last_at: string | null
  last_message: string | null
  unread_count: number
}

export interface Message {
  id: number | string
  direction: 'in' | 'out'
  body: string
  ts: string | null
  status: string
  msg_type?: 'text' | 'image' | 'document' | 'audio' | 'video'
  media_url?: string | null
  mime_type?: string | null
  filename?: string | null
}
