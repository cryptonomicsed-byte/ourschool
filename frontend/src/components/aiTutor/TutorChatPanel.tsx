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

import { useState, useEffect, useRef, useCallback } from 'react'
import { Bot, Sparkles, GraduationCap, X } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import { api, getErrorMessage } from '../../services/api'
import { Button, TextArea, Spinner, EmptyState } from '../ui'
import MarkdownRenderer from '../common/MarkdownRenderer'

// ─── Types ───────────────────────────────────────────────────────────────────

type Capability = 'chat' | 'mastery_path'

interface TutorBook {
  id: string
  title: string
}

interface ChatMessage {
  id: string
  role: 'student' | 'tutor'
  text: string
  streaming?: boolean
}

interface TutorEvent {
  type: string
  content?: string
  metadata?: { response?: string; [key: string]: unknown }
}

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error'

// ─── Panel ───────────────────────────────────────────────────────────────────
// The live AI Tutor chat — this is where a student actually does the work:
// asking questions, or switching to "Quiz me" so the tutor asks questions,
// grades her answers, and updates her real gradebook entries.

interface AssignmentContext {
  title: string
  instructions: string
  subjectName?: string
}

interface TutorChatPanelProps {
  onClose?: () => void
  /** When set, scopes the tutor to a specific assignment: auto-selects the
   * matching subject book and opens with the assignment's instructions
   * already in context, instead of a blank chat. */
  assignmentContext?: AssignmentContext
  /** Hides the standalone header/close affordance when embedded inside
   * another panel (e.g. AssignmentWorkspace) that already has its own chrome. */
  embedded?: boolean
  /** A message to send as soon as the tutor is connected — set/cleared by a
   * parent that wants to trigger a specific turn (e.g. "review my draft",
   * "explain my grade") from a button outside this component, without
   * duplicating the WS plumbing. */
  queuedMessage?: string
  onQueuedMessageSent?: () => void
}

export default function TutorChatPanel({
  onClose,
  assignmentContext,
  embedded,
  queuedMessage,
  onQueuedMessageSent,
}: TutorChatPanelProps) {
  const { user } = useAuth()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [capability, setCapability] = useState<Capability>('chat')
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [connectError, setConnectError] = useState<string | null>(null)
  const [turnInFlight, setTurnInFlight] = useState(false)
  const [books, setBooks] = useState<TutorBook[]>([])
  const [bookId, setBookId] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const primedRef = useRef(false)
  const wasOpenRef = useRef(false)

  const wsRef = useRef<WebSocket | null>(null)
  const streamingIdRef = useRef<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const appendOrUpdateStreaming = useCallback((delta: string) => {
    setMessages((prev) => {
      const id = streamingIdRef.current
      if (!id) return prev
      return prev.map((m) => (m.id === id ? { ...m, text: m.text + delta } : m))
    })
  }, [])

  const finalizeStreaming = useCallback((finalText?: string) => {
    setMessages((prev) => {
      const id = streamingIdRef.current
      if (!id) return prev
      return prev.map((m) =>
        m.id === id
          ? { ...m, text: finalText && finalText.trim() ? finalText : m.text, streaming: false }
          : m
      )
    })
    streamingIdRef.current = null
    setTurnInFlight(false)
  }, [])

  useEffect(() => {
    if (!user) return
    let cancelled = false

    const connect = async () => {
      setConnection('connecting')
      setConnectError(null)
      try {
        const [{ token, ws_url: wsUrl }, booksResp] = await Promise.all([
          api.post(`/ai/tutor/${user.id}/token`),
          api.get(`/ai/tutor/${user.id}/books`).catch(() => ({ books: [] })),
        ])
        if (cancelled) return
        const fetchedBooks: TutorBook[] = booksResp.books || []
        setBooks(fetchedBooks)
        const subjectHint = assignmentContext?.subjectName?.toLowerCase()
        const matched = subjectHint
          ? fetchedBooks.find((b) => b.title.toLowerCase().includes(subjectHint))
          : undefined
        setBookId((prev) => prev ?? matched?.id ?? fetchedBooks[0]?.id ?? null)

        const ws = new WebSocket(`${wsUrl}?token=${encodeURIComponent(token)}`)
        wsRef.current = ws

        ws.onopen = () => {
          wasOpenRef.current = true
          setConnection('open')
        }
        ws.onerror = () => setConnection('error')
        ws.onclose = () => {
          if (cancelled) return
          setConnection('closed')
          // The tutor backend has intermittently hung mid-session (known
          // infra issue, not a user action) — recover automatically once
          // instead of leaving the student staring at a dead chat.
          if (wasOpenRef.current) {
            wasOpenRef.current = false
            autoRetryTimerRef.current = setTimeout(() => setRetryToken((t) => t + 1), 2500)
          }
        }

        ws.onmessage = (event) => {
          let data: TutorEvent
          try {
            data = JSON.parse(event.data)
          } catch {
            return
          }
          if (data.type === 'content' && data.content) {
            appendOrUpdateStreaming(data.content)
          } else if (data.type === 'result') {
            finalizeStreaming(data.metadata?.response)
          } else if (data.type === 'error') {
            finalizeStreaming(
              `Sorry, something went wrong: ${data.content || 'unknown error'}`
            )
          }
        }
      } catch (err) {
        if (!cancelled) {
          setConnection('error')
          setConnectError(getErrorMessage(err))
        }
      }
    }

    connect()
    return () => {
      cancelled = true
      if (autoRetryTimerRef.current) clearTimeout(autoRetryTimerRef.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [user, appendOrUpdateStreaming, finalizeStreaming, retryToken])

  const retry = useCallback(() => {
    setRetryToken((t) => t + 1)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const sendText = useCallback(
    (text: string, cap: Capability) => {
      if (!text || connection !== 'open' || turnInFlight || !wsRef.current || !bookId) return

      const studentMsg: ChatMessage = { id: `s-${Date.now()}`, role: 'student', text }
      const tutorMsgId = `t-${Date.now()}`
      streamingIdRef.current = tutorMsgId
      setMessages((prev) => [
        ...prev,
        studentMsg,
        { id: tutorMsgId, role: 'tutor', text: '', streaming: true },
      ])
      setTurnInFlight(true)

      wsRef.current.send(
        JSON.stringify({
          type: 'message',
          content: text,
          capability: cap,
          book_references: [{ book_id: bookId }],
        })
      )
    },
    [connection, turnInFlight, bookId]
  )

  const send = () => {
    const text = draft.trim()
    if (!text) return
    sendText(text, capability)
    setDraft('')
  }

  // Prime the conversation once with the assignment's own instructions so
  // the tutor can help without the student having to retype/explain them.
  useEffect(() => {
    if (!assignmentContext || primedRef.current) return
    if (connection !== 'open' || !bookId) return
    // A caller-supplied queuedMessage (e.g. "review my draft") takes the
    // place of the generic opener instead of stacking both.
    if (queuedMessage) {
      primedRef.current = true
      return
    }
    primedRef.current = true
    sendText(
      `I'm working on this assignment: "${assignmentContext.title}".\n\n` +
        `Instructions: ${assignmentContext.instructions}\n\n` +
        `Can you help me understand what to do first?`,
      'chat'
    )
  }, [assignmentContext, connection, bookId, sendText])

  useEffect(() => {
    if (!queuedMessage || connection !== 'open' || !bookId) return
    sendText(queuedMessage, capability)
    onQueuedMessageSent?.()
  }, [queuedMessage, connection, bookId, capability, sendText, onQueuedMessageSent])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  if (!user) return null

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-2 shrink-0 gap-2">
        {!embedded && (
          <div className="flex items-center gap-2 min-w-0">
            <Bot className="w-5 h-5 text-accent shrink-0" />
            <h2 className="text-[14px] font-semibold text-ink truncate">AI Tutor</h2>
          </div>
        )}
        <div className="flex items-center gap-2 shrink-0 ml-auto">
          <div className="flex gap-1 bg-panel-2 rounded-pill p-1">
            <button
              onClick={() => setCapability('chat')}
              className={`px-2.5 py-1 rounded-pill text-[11.5px] font-medium flex items-center gap-1 transition ${
                capability === 'chat' ? 'bg-accent text-white' : 'text-ink-2 hover:text-ink'
              }`}
            >
              <Sparkles className="w-3 h-3" /> Chat
            </button>
            <button
              onClick={() => setCapability('mastery_path')}
              className={`px-2.5 py-1 rounded-pill text-[11.5px] font-medium flex items-center gap-1 transition ${
                capability === 'mastery_path' ? 'bg-accent text-white' : 'text-ink-2 hover:text-ink'
              }`}
            >
              <GraduationCap className="w-3 h-3" /> Quiz me
            </button>
          </div>
          {onClose && (
            <button onClick={onClose} aria-label="Close AI Tutor" className="text-ink-2 hover:text-ink">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Subject picker gets its own row so it never competes for space with
          the Chat/Quiz toggle above (that's what was overlapping). Hidden
          when scoped to a specific assignment — the book is already locked
          to that assignment's subject. */}
      {!assignmentContext && books.length > 1 && (
        <div className="mb-2 shrink-0">
          <select
            value={bookId ?? ''}
            onChange={(e) => setBookId(e.target.value)}
            className="w-full text-[11.5px] font-medium rounded-field bg-panel-2 border border-line px-2 py-1.5 text-ink"
            aria-label="Subject"
          >
            {books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.title}
              </option>
            ))}
          </select>
        </div>
      )}

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-field border border-line bg-panel p-3 space-y-3 min-h-0"
      >
        {connection === 'connecting' && messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <Spinner size="md" />
          </div>
        )}
        {connection === 'error' && messages.length === 0 && (
          <EmptyState
            icon={Bot}
            size="sm"
            title="Couldn't connect to the AI Tutor"
            subtext={connectError || 'The tutor service may be offline. Try again in a moment.'}
            action={
              <Button variant="secondary" size="sm" onClick={retry}>
                Try Again
              </Button>
            }
          />
        )}
        {(connection === 'closed' || connection === 'error') && messages.length > 0 && (
          <div className="flex items-center justify-center gap-2 py-2 text-[12px] text-muted">
            <Spinner size="sm" /> Reconnecting to your AI Tutor...
          </div>
        )}
        {connection === 'open' && messages.length === 0 && (
          <EmptyState
            icon={Bot}
            size="sm"
            title="Say hi to your AI Tutor"
            subtext='Ask a question, or switch to "Quiz me" to practice and get graded.'
          />
        )}
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === 'student' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-field px-3 py-2 text-[12.5px] ${
                m.role === 'student'
                  ? 'bg-accent text-white'
                  : 'bg-panel-2 text-ink border border-line'
              }`}
            >
              {m.role === 'tutor' ? (
                <MarkdownRenderer content={m.text || (m.streaming ? '…' : '')} />
              ) : (
                <span className="whitespace-pre-wrap">{m.text}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2.5 flex gap-2 items-end shrink-0">
        <TextArea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            capability === 'mastery_path'
              ? 'Ask to be quizzed, or answer a question...'
              : 'Ask your AI tutor anything...'
          }
          disabled={connection !== 'open'}
          rows={2}
          fullWidth
          resize="none"
        />
        <Button
          onClick={send}
          disabled={connection !== 'open' || turnInFlight || !draft.trim() || !bookId}
          loading={turnInFlight}
          size="sm"
        >
          Send
        </Button>
      </div>
    </div>
  )
}
