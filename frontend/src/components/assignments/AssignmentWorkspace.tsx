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

import { useEffect, useState } from 'react'
import { Clock, Award, Bot, Send, CheckCircle, X } from 'lucide-react'
import { StudentAssignment, Subject } from '../../types'
import { assignmentsApi, assignmentUtils } from '../../services/assignments'
import { getErrorMessage } from '../../services/api'
import { Button, TextArea, Spinner } from '../ui'
import MarkdownRenderer from '../common/MarkdownRenderer'
import TutorChatPanel from '../aiTutor/TutorChatPanel'

interface AssignmentWorkspaceProps {
  assignment: StudentAssignment
  subject?: Subject
  isOpen: boolean
  onClose: () => void
  onSubmitted: (updated: StudentAssignment) => void
}

export default function AssignmentWorkspace({
  assignment,
  subject,
  isOpen,
  onClose,
  onSubmitted,
}: AssignmentWorkspaceProps) {
  const [submissionNotes, setSubmissionNotes] = useState(assignment.submission_notes || '')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showTutor, setShowTutor] = useState(false)
  const [queuedMessage, setQueuedMessage] = useState<string | undefined>(undefined)

  const template = assignment.template
  const alreadySubmitted = assignment.status === 'submitted' || assignment.status === 'graded'

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isOpen, onClose])

  const handleSubmit = async () => {
    try {
      setSubmitting(true)
      setError(null)
      if (assignment.status === 'not_started') {
        await assignmentsApi.startAssignment(assignment.id)
      }
      const updated = await assignmentsApi.completeAssignment(assignment.id, submissionNotes)
      onSubmitted(updated)
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to submit assignment'))
    } finally {
      setSubmitting(false)
    }
  }

  const askTutorToReviewDraft = () => {
    setShowTutor(true)
    setQueuedMessage(
      `Can you look over my work so far and give me feedback before I submit? Here's what I have:\n\n${submissionNotes}`
    )
  }

  const askTutorAboutGrade = () => {
    setShowTutor(true)
    setQueuedMessage(
      `I just got graded on this assignment: ${assignment.letter_grade} (${assignment.percentage_grade?.toFixed(1)}%). ` +
        `Feedback: ${assignment.teacher_feedback || 'none given'}. Can you help me understand what I got wrong and how to improve?`
    )
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="w-full max-w-6xl h-[85vh] bg-panel border border-line rounded-panel shadow-xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line shrink-0">
          <h2 className="text-[16px] font-semibold text-ink truncate pr-4">
            {template?.name || 'Assignment'}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-faint hover:text-ink shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 p-5 flex-1 min-h-0">
        {/* Left: instructions + submission */}
        <div className="flex flex-col min-h-0 overflow-y-auto pr-1">
          <div className="flex items-center gap-3 text-[12.5px] text-muted mb-4">
            {subject && (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: subject.color }} />
                {subject.name}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Award className="w-3.5 h-3.5" /> {assignment.custom_max_points || template?.max_points || 0} pts
            </span>
            {template?.estimated_duration_minutes && (
              <span className="flex items-center gap-1">
                <Clock className="w-3.5 h-3.5" /> {assignmentUtils.formatDuration(template.estimated_duration_minutes)}
              </span>
            )}
          </div>

          <div className="bg-panel-2 border border-line rounded-card-lg p-4 mb-4">
            <p className="text-[11px] font-semibold text-faint uppercase tracking-wide mb-2">Instructions</p>
            <MarkdownRenderer content={template?.instructions || template?.description || 'No instructions provided.'} />
          </div>

          {assignment.is_graded ? (
            <div className="bg-pos-bg border border-[var(--pos-fg)]/20 rounded-card-lg p-4">
              <p className="text-[13px] font-semibold text-pos-fg mb-1 flex items-center gap-1.5">
                <CheckCircle className="w-4 h-4" /> Graded: {assignment.letter_grade} ({assignment.percentage_grade?.toFixed(1)}%)
              </p>
              {assignment.teacher_feedback && (
                <MarkdownRenderer content={assignment.teacher_feedback} className="text-[13px] text-ink mt-2" />
              )}
              <Button
                variant="secondary"
                size="sm"
                onClick={askTutorAboutGrade}
                icon={<Bot className="w-3.5 h-3.5" />}
                className="mt-3"
              >
                Talk to my AI Tutor about this
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <label className="text-[11px] font-semibold text-faint uppercase tracking-wide">
                Your Work
              </label>
              <TextArea
                value={submissionNotes}
                onChange={(e) => setSubmissionNotes(e.target.value)}
                placeholder="Write your answer or notes here before submitting..."
                rows={8}
                disabled={alreadySubmitted || submitting}
                fullWidth
              />
              {error && <p className="text-[12.5px] text-neg-fg">{error}</p>}
              {!alreadySubmitted && (
                <div className="flex gap-2">
                  <Button
                    onClick={handleSubmit}
                    loading={submitting}
                    disabled={!submissionNotes.trim()}
                    icon={<Send className="w-4 h-4" />}
                  >
                    {submitting ? 'Submitting...' : 'Submit Assignment'}
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={askTutorToReviewDraft}
                    disabled={!submissionNotes.trim()}
                    icon={<Bot className="w-4 h-4" />}
                  >
                    Review my work first
                  </Button>
                </div>
              )}
              {alreadySubmitted && !assignment.is_graded && (
                <div className="text-[13px] text-muted flex items-center gap-2">
                  <Spinner size="sm" /> Submitted — the AI Tutor is grading this now.
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: AI Tutor, scoped to this assignment */}
        <div className="flex flex-col min-h-0 border border-line rounded-card-lg bg-panel-2 p-3">
          {!showTutor ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-6">
              <Bot className="w-8 h-8 text-accent" />
              <p className="text-[13px] text-muted">
                Stuck? Your AI Tutor already knows what this assignment is about and can walk
                through it with you.
              </p>
              <Button onClick={() => setShowTutor(true)} icon={<Bot className="w-4 h-4" />}>
                Ask the AI Tutor for help
              </Button>
            </div>
          ) : (
            <TutorChatPanel
              embedded
              assignmentContext={{
                title: template?.name || 'Assignment',
                instructions: template?.instructions || template?.description || '',
                subjectName: subject?.name,
              }}
              queuedMessage={queuedMessage}
              onQueuedMessageSent={() => setQueuedMessage(undefined)}
            />
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
