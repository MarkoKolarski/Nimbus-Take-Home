export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

let onUnauthorized: (() => void) | null = null

// Called once from App on mount so any 401 anywhere — not just the initial
// /auth/me check — drops the UI back to the login screen instead of leaving
// every component to handle session expiry on its own.
export function setUnauthorizedHandler(fn: (() => void) | null): void {
  onUnauthorized = fn
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!res.ok) {
    let detail: unknown
    try {
      detail = (await res.json()).detail
    } catch {
      detail = res.statusText
    }
    if (res.status === 401 && path !== '/auth/me') onUnauthorized?.()
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export interface User {
  id: string
  email: string
  display_name: string
}

export interface Datasource {
  id: string
  kind: string
  name: string
  created_at: string
}

export interface S3Config {
  endpoint_url: string
  bucket_name: string
  access_key_id: string
  secret_access_key: string
  region_name: string
}

export interface Directory {
  id: string
  datasource_id: string
  prefix: string
  created_at: string
}

export interface SyncJob {
  id: string
  directory_id: string
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'partial'
  stats: Record<string, number>
  error_count: number
  queued_at: string
  started_at: string | null
  finished_at: string | null
  attempt: number
}

export interface DocumentRow {
  id: string
  filename: string
  source_key: string
  state: string
  error: string | null
  indexed_at: string | null
}

export interface Citation {
  number: number
  filenames: string[]
}

export interface ChatReply {
  answer: string
  citations: Citation[]
}

export const login = (email: string, password: string) =>
  request<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })

export const logout = () => request<{ status: string }>('/auth/logout', { method: 'POST' })

export const me = () => request<User>('/auth/me')

export const listDatasources = () => request<Datasource[]>('/datasources')

export const createDatasource = (name: string, config: S3Config) =>
  request<Datasource>('/datasources', {
    method: 'POST',
    body: JSON.stringify({ kind: 's3', name, config }),
  })

export const browseDatasource = (datasourceId: string, prefix: string) =>
  request<string[]>(`/datasources/${datasourceId}/browse?prefix=${encodeURIComponent(prefix)}`)

export const listDirectories = (datasourceId: string) =>
  request<Directory[]>(`/datasources/${datasourceId}/directories`)

export const registerDirectory = (datasourceId: string, prefix: string) =>
  request<Directory>(`/datasources/${datasourceId}/directories`, {
    method: 'POST',
    body: JSON.stringify({ prefix }),
  })

export const deleteDirectory = (directoryId: string) =>
  request<void>(`/directories/${directoryId}`, { method: 'DELETE' })

export const enqueueSync = (directoryId: string) =>
  request<SyncJob>(`/directories/${directoryId}/sync`, { method: 'POST' })

export const getSyncStatus = (directoryId: string) =>
  request<SyncJob>(`/directories/${directoryId}/sync`)

export const listDocuments = (directoryId: string) =>
  request<DocumentRow[]>(`/directories/${directoryId}/documents`)

export const deleteDocument = (documentId: string) =>
  request<void>(`/documents/${documentId}`, { method: 'DELETE' })

export const postChatMessage = (message: string) =>
  request<ChatReply>('/chat/messages', { method: 'POST', body: JSON.stringify({ message }) })
