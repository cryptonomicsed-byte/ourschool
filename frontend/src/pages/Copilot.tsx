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
import { Bot, Send, CheckCircle, XCircle, Clock, AlertTriangle, Sparkles } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { copilotApi, CopilotMessage, CopilotProposal } from '../services/copilot'
import { getErrorMessage } from '../services/api'
import { Button, TextArea, Spinner, EmptyState, Pill } from '../components/ui'
import MarkdownRenderer from '../components/common/MarkdownRenderer'

interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  text: string
  streaming?: boolean
}

const proposalStatusVariant = (status: string) => {
  switch (status) {
    case 'pending':
      return 'bg-accent/10 text-accent border border-accent/20'
    case 'approved':
      return 'bg-pos-bg text-pos-fg border border-[var(--pos-fg)]/20'
    case 'rejected':
      return 'bg-track text-faint border border-line'
    case 'failed':
      return 'bg-neg-bg text-neg-fg border border-[var(--neg-fg)]/20'
    default:
      return 'bg-track text-faint border border-line'
  }
}

export default function Copilot() {
  const { user } = useAuth()
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)
  const [proposals, setProposals] = useState<CopilotProposal[]>([])
  const [proposalsLoading, setProposalsLoading] = useState(true)
  const [decidingId, setDecidingId] = useState<number | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const streamingIdRef = useRef<string | null>(null)

  const loadProposals = useCallback(() => {
    setProposalsLoading(true)
    copilotApi
      .listProposals()
      .then(setProposals)
      .catch(() => {
        // Non-fatal: the proposals panel just stays empty on failure.
      })
      .finally(() => setProposalsLoading(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    copilotApi
      .listConversations()
      .then(async (convos) => {
        if (cancelled) return
        const existing = convos[0]
        const conv = existing || (await copilotApi.createConversation())
        if (cancelled) return
        setConversationId(conv.id)
        const history = await copilotApi.listMessages(conv.id)
        if (cancelled) return
        setMessages(
          history.map((m: CopilotMessage) => ({ id: `h-${m.id}`, role: m.role, text: m.content }))
        )
      })
      .catch((err) => {
        if (!cancelled) setInitError(getErrorMessage(err, 'Failed to load copilot'))
      })
    // Only the parent approves proposals; a student's chat can still create
    // them (the agent may propose something on her behalf), but she has no
    // approve/reject UI, so there's nothing for her to load here.
    if (user?.role === 'admin') loadProposals()
    else setProposalsLoading(false)
    return () => {
      cancelled = true
    }
  }, [loadProposals, user?.role])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const text = draft.trim()
    if (!text || !conversationId || sending) return

    const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: 'user', text }
    const agentMsgId = `a-${Date.now()}`
    streamingIdRef.current = agentMsgId
    setMessages((prev) => [...prev, userMsg, { id: agentMsgId, role: 'agent', text: '', streaming: true }])
    setDraft('')
    setSending(true)

    try {
      await copilotApi.streamChat(
        conversationId,
        text,
        (delta) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === agentMsgId ? { ...m, text: m.text + delta } : m))
          )
        },
        (fullContent, pendingProposals) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === agentMsgId ? { ...m, text: fullContent, streaming: false } : m))
          )
          if (pendingProposals > 0) loadProposals()
        }
      )
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === agentMsgId
            ? { ...m, text: `Sorry, something went wrong: ${getErrorMessage(err)}`, streaming: false }
            : m
        )
      )
    } finally {
      setSending(false)
      streamingIdRef.current = null
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const decide = async (proposal: CopilotProposal, approve: boolean) => {
    try {
      setDecidingId(proposal.id)
      if (approve) {
        await copilotApi.approveProposal(proposal.id)
      } else {
        await copilotApi.rejectProposal(proposal.id)
      }
      loadProposals()
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: 'agent',
          text: `Couldn't ${approve ? 'approve' : 'reject'} that proposal: ${getErrorMessage(err)}`,
        },
      ])
    } finally {
      setDecidingId(null)
    }
  }

  if (!user) return null

  const isAdmin = user.role === 'admin'
  const pendingProposals = proposals.filter((p) => p.status === 'pending')
  const decidedProposals = proposals.filter((p) => p.status !== 'pending')

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-semibold text-faint uppercase tracking-[.06em] mb-0.5">
          Copilot
        </p>
        <h1 className="text-[26px] font-semibold text-ink tracking-[-0.02em]">
          {isAdmin ? "Your household's school agent" : 'Your AI teacher'}
        </h1>
        <p className="mt-1 text-[13px] text-muted">
          {isAdmin
            ? "Ask anything about the school — it's grounded in your real data. It can never write " +
              'anything on its own: it proposes changes here for you to approve.'
            : "Ask your copilot anything — it knows your real grades, mastery, and coursework, and it's " +
              'here to teach and help, not just answer. It can never change anything on its own; if it ' +
              'suggests logging or grading something, your parent has to approve it first.'}
        </p>
      </div>

      <div className={`grid grid-cols-1 gap-5 ${isAdmin ? 'lg:grid-cols-3' : ''}`}>
        {/* Chat */}
        <div className={`${isAdmin ? 'lg:col-span-2' : ''} flex flex-col h-[65vh] bg-panel border border-line rounded-card-lg p-4`}>
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto rounded-field border border-line bg-panel-2 p-3 space-y-3 min-h-0"
          >
            {initError && <EmptyState icon={AlertTriangle} title="Couldn't load copilot" subtext={initError} />}
            {!initError && messages.length === 0 && (
              <EmptyState
                icon={Bot}
                size="sm"
                title="Ask your copilot anything"
                subtext={
                  isAdmin
                    ? 'e.g. "How is Jalayna doing this term?" or "Mark her present today."'
                    : 'e.g. "Can you help me with my Science homework?" or "Quiz me on ratios."'
                }
              />
            )}
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={`max-w-[85%] rounded-field px-3 py-2 text-[12.5px] ${
                    m.role === 'user'
                      ? 'bg-accent text-white'
                      : 'bg-panel text-ink border border-line'
                  }`}
                >
                  {m.role === 'agent' ? (
                    <MarkdownRenderer content={m.text || (m.streaming ? '…' : '')} />
                  ) : (
                    <span className="whitespace-pre-wrap">{m.text}</span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-3 flex gap-2 items-end shrink-0">
            <TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask your copilot..."
              disabled={!conversationId || sending}
              rows={2}
              fullWidth
              resize="none"
            />
            <Button onClick={send} disabled={!conversationId || sending || !draft.trim()} loading={sending} size="sm">
              <Send className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* Proposals — parent-only; a student's chat can still create a
            proposal, but only the parent approves it. */}
        {isAdmin && (
        <div className="flex flex-col h-[65vh] bg-panel border border-line rounded-card-lg p-4">
          <div className="flex items-center gap-2 mb-3 shrink-0">
            <Sparkles className="w-4 h-4 text-accent" />
            <h2 className="text-[14px] font-semibold text-ink">Awaiting your approval</h2>
            {pendingProposals.length > 0 && (
              <Pill variant="accent">{pendingProposals.length}</Pill>
            )}
          </div>

          <div className="flex-1 overflow-y-auto space-y-3 min-h-0">
            {proposalsLoading && (
              <div className="flex items-center justify-center py-8">
                <Spinner size="sm" />
              </div>
            )}

            {!proposalsLoading && pendingProposals.length === 0 && (
              <p className="text-[12.5px] text-muted text-center py-8">
                Nothing waiting on you right now.
              </p>
            )}

            {pendingProposals.map((p) => (
              <div key={p.id} className="border border-accent/20 bg-accent/5 rounded-field p-3">
                <p className="text-[11px] font-semibold text-accent uppercase tracking-wide mb-1">
                  {p.tool_name.replace('school_propose_', '').replace(/_/g, ' ')}
                </p>
                <p className="text-[12.5px] text-ink mb-3">{p.summary || JSON.stringify(p.args)}</p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => decide(p, true)}
                    loading={decidingId === p.id}
                    icon={<CheckCircle className="w-3.5 h-3.5" />}
                  >
                    Approve
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => decide(p, false)}
                    disabled={decidingId === p.id}
                    icon={<XCircle className="w-3.5 h-3.5" />}
                  >
                    Reject
                  </Button>
                </div>
              </div>
            ))}

            {decidedProposals.length > 0 && (
              <div className="pt-3 mt-3 border-t border-line">
                <p className="text-[11px] font-semibold text-faint uppercase tracking-wide mb-2">
                  Recent decisions
                </p>
                <div className="space-y-2">
                  {decidedProposals.slice(0, 10).map((p) => (
                    <div key={p.id} className="flex items-center gap-2 text-[12px] text-muted">
                      <span
                        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase ${proposalStatusVariant(p.status)}`}
                      >
                        {p.status === 'pending' && <Clock className="w-3 h-3" />}
                        {p.status}
                      </span>
                      <span className="truncate">{p.summary || p.tool_name}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
        )}
      </div>
    </div>
  )
}
