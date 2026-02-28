import client from './client'
import type { Chat, Message } from '../types'

export async function getChats(): Promise<Chat[]> {
  const res = await client.get('/chats')
  return res.data
}

export async function getMessages(contactKey: string): Promise<Message[]> {
  const res = await client.get(`/chats/${encodeURIComponent(contactKey)}/messages`)
  return res.data
}

export async function sendMessage(contactKey: string, text: string): Promise<{ id: number }> {
  const res = await client.post(`/chats/${encodeURIComponent(contactKey)}/send`, { text })
  return res.data
}

export async function markRead(contactKey: string): Promise<void> {
  await client.post(`/chats/${encodeURIComponent(contactKey)}/mark_read`)
}

export async function newChat(phone: string, nome?: string): Promise<{ contact_key: string; id: number }> {
  const res = await client.post('/chats/new', { phone, nome })
  return res.data
}

export async function saveCompanySettings(data: { business_phone?: string }): Promise<void> {
  await client.post('/settings/company', data)
}
