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

import { useEffect, useState, useCallback } from 'react'
import { Award, Clock, Sparkles, LayoutGrid } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { assignmentsApi, assignmentUtils } from '../services/assignments'
import { subjectsApi } from '../services/subjects'
import { StudentAssignment, Subject } from '../types'
import { getErrorMessage } from '../services/api'
import { Spinner, EmptyState } from '../components/ui'
import MarkdownRenderer from '../components/common/MarkdownRenderer'
import AssignmentWorkspace from '../components/assignments/AssignmentWorkspace'

const statusLabel: Record<string, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  submitted: 'Waiting for grade',
  graded: 'Graded',
  overdue: 'Overdue',
  excused: 'Excused',
}

const statusColor: Record<string, string> = {
  not_started: 'bg-track text-faint border border-line',
  in_progress: 'bg-accent/10 text-accent border border-accent/20',
  submitted: 'bg-track text-muted border border-line',
  graded: 'bg-pos-bg text-pos-fg border border-[var(--pos-fg)]/20',
  overdue: 'bg-neg-bg text-neg-fg border border-[var(--neg-fg)]/20',
  excused: 'bg-track text-faint border border-line',
}

export default function Workboard() {
  const { user } = useAuth()
  const [assignments, setAssignments] = useState<StudentAssignment[]>([])
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeAssignment, setActiveAssignment] = useState<StudentAssignment | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    Promise.all([assignmentsApi.getMyAssignments(), subjectsApi.getAll()])
      .then(([a, s]) => {
        // Cards are a workboard of what's still open — graded/excused work
        // belongs in Assignments (the full history list), not here.
        setAssignments(
          a.filter((x) => x.status !== 'graded' && x.status !== 'excused')
        )
        setSubjects(s)
      })
      .catch((err) => setError(getErrorMessage(err, 'Failed to load your assignments')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const subjectFor = (a: StudentAssignment) =>
    subjects.find((s) => s.id === a.template?.subject_id)

  const handleSubmitted = (updated: StudentAssignment) => {
    setAssignments((prev) =>
      updated.status === 'graded' || updated.status === 'excused'
        ? prev.filter((a) => a.id !== updated.id)
        : prev.map((a) => (a.id === updated.id ? updated : a))
    )
    setActiveAssignment(null)
  }

  if (!user) return null

  return (
    <div className="space-y-6">
      <div>
        <p className="text-[11px] font-semibold text-faint uppercase tracking-[.06em] mb-0.5">
          Workboard
        </p>
        <h1 className="text-[26px] font-semibold text-ink tracking-[-0.02em]">
          Pick your next assignment
        </h1>
        <p className="mt-1 text-[13px] text-muted">
          Click a card to open it, do the work, and get help from your AI Tutor right there.
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-muted">
          <Spinner size="sm" /> Loading your assignments...
        </div>
      )}

      {!loading && error && (
        <EmptyState icon={LayoutGrid} title="Couldn't load your workboard" subtext={error} />
      )}

      {!loading && !error && assignments.length === 0 && (
        <EmptyState
          icon={Sparkles}
          title="Nothing on your workboard right now"
          subtext="Check back soon — new assignments show up here as they're planned."
        />
      )}

      {!loading && !error && assignments.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {assignments.map((a) => {
            const subject = subjectFor(a)
            const template = a.template
            return (
              <button
                key={a.id}
                onClick={() => setActiveAssignment(a)}
                className="text-left bg-panel border border-line rounded-card-lg overflow-hidden hover:border-accent/40 hover:shadow-md transition-all"
              >
                <div className="h-1.5" style={{ backgroundColor: subject?.color || 'var(--accent)' }} />
                <div className="p-5">
                  <div className="flex items-start justify-between mb-2 gap-2">
                    <h3 className="text-[15px] font-semibold text-ink leading-snug">
                      {template?.name}
                    </h3>
                    <span
                      className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-[10.5px] font-semibold uppercase tracking-wide ${statusColor[a.status]}`}
                    >
                      {statusLabel[a.status]}
                    </span>
                  </div>
                  <p className="text-[12px] text-muted mb-3">{subject?.name}</p>
                  {template?.description && (
                    <div className="text-[12.5px] text-muted mb-3 line-clamp-2">
                      <MarkdownRenderer content={template.description} className="line-clamp-2" />
                    </div>
                  )}
                  <div className="flex items-center gap-3 text-[12px] text-muted">
                    <span className="flex items-center gap-1">
                      <Award className="w-3.5 h-3.5" /> {a.custom_max_points || template?.max_points || 0} pts
                    </span>
                    {template?.estimated_duration_minutes && (
                      <span className="flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" />
                        {assignmentUtils.formatDuration(template.estimated_duration_minutes)}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}

      {activeAssignment && (
        <AssignmentWorkspace
          assignment={activeAssignment}
          subject={subjectFor(activeAssignment)}
          isOpen={!!activeAssignment}
          onClose={() => setActiveAssignment(null)}
          onSubmitted={handleSubmitted}
        />
      )}
    </div>
  )
}
