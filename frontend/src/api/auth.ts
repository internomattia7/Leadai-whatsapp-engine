import client from './client'
import type { User } from '../types'

export async function login(email: string, password: string): Promise<User> {
  const res = await client.post('/auth/login', { email, password })
  return res.data.user
}

export async function logout(): Promise<void> {
  await client.post('/auth/logout')
}

export async function me(): Promise<User> {
  const res = await client.get('/me')
  return res.data
}
