/*
 * OurSchool - Homeschool Management System
 * Copyright (C) 2025 Dustan Ashley
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

import { config } from '../config/env'
import { STORAGE_KEYS } from '../constants/auth'
import { api } from './api'

const API_BASE = config.api.baseUrl

export interface CopilotConversation {
  id: number
  user_id: number
  title: string
  created_at: string
  updated_at: string
}

export interface CopilotMessage {
  id: number
  conversation_id: number
  role: 'user' | 'agent'
  content: string
  created_at: string
}

export interface CopilotProposal {
  id: number
  tool_name: string
  args: Record<string, unknown>
  summary: string
  status: 'pending' | 'approved' | 'rejected' | 'failed'
  created_at: string
  decided_at?: string
  decided_by?: number
  result?: Record<string, unknown>
}

type SSEEvent =
  | { type: 'delta'; content: string }
  | { type: 'done'; content: string; pending_proposals: number }

export const copilotApi = {
  createConversation: (title?: string): Promise<CopilotConversation> =>
    api.post('/copilot/conversations', { title }),

  listConversations: (): Promise<CopilotConversation[]> => api.get('/copilot/conversations'),

  listMessages: (conversationId: number): Promise<CopilotMessage[]> =>
    api.get(`/copilot/conversations/${conversationId}/messages`),

  listProposals: (status?: string): Promise<CopilotProposal[]> =>
    api.get(`/copilot/proposals${status ? `?status=${status}` : ''}`),

  approveProposal: (proposalId: number): Promise<CopilotProposal> =>
    api.post(`/copilot/proposals/${proposalId}/approve`, {}),

  rejectProposal: (proposalId: number, reason?: string): Promise<CopilotProposal> =>
    api.post(`/copilot/proposals/${proposalId}/reject`, { reason }),

  /**
   * Streams the copilot's reply via SSE. Calls `onDelta` as chunks arrive
   * and `onDone` with the full text + updated pending-proposal count.
   * Fetch + ReadableStream rather than EventSource because this needs a
   * POST body and an Authorization header, neither of which EventSource
   * supports.
   */
  async streamChat(
    conversationId: number,
    message: string,
    onDelta: (content: string) => void,
    onDone: (fullContent: string, pendingProposals: number) => void
  ): Promise<void> {
    const token = localStorage.getItem(STORAGE_KEYS.TOKEN)
    const response = await fetch(`${API_BASE}/copilot/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ conversation_id: conversationId, message }),
    })

    if (!response.ok || !response.body) {
      let detail = `Copilot request failed: ${response.status}`
      try {
        const data = await response.json()
        if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
      } catch {
        // ignore, use default message
      }
      throw new Error(detail)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const rawEvent = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')

        const line = rawEvent.split('\n').find((l) => l.startsWith('data: '))
        if (!line) continue
        try {
          const event: SSEEvent = JSON.parse(line.slice('data: '.length))
          if (event.type === 'delta') {
            onDelta(event.content)
          } else if (event.type === 'done') {
            onDone(event.content, event.pending_proposals)
          }
        } catch {
          // skip malformed event
        }
      }
    }
  },
}
