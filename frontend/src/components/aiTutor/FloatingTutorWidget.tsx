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

import { useState } from 'react'
import { Bot, X } from 'lucide-react'
import TutorChatPanel from './TutorChatPanel'


/**
 * Persistent bottom-right chat bubble for the AI Tutor, available on every
 * page for a logged-in student — this is how she actually does AI-tutor
 * assigned work: chatting/quizzing live with the tutor, not just seeing a
 * grade appear after the fact.
 */
export default function FloatingTutorWidget() {
  const [open, setOpen] = useState(false)

  return (
    <>
      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-[380px] max-w-[calc(100vw-3rem)] h-[560px] max-h-[calc(100vh-8rem)] bg-panel border border-line rounded-panel shadow-xl p-3 flex flex-col">
          <TutorChatPanel onClose={() => setOpen(false)} />
        </div>
      )}

      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Open AI Tutor chat"
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-accent text-white shadow-lg flex items-center justify-center hover:opacity-90 transition"
      >
        {open ? <X className="w-6 h-6" /> : <Bot className="w-6 h-6" />}
      </button>
    </>
  )
}
