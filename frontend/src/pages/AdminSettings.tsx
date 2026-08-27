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

import React, { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { settingsApi } from '../services/settings'
import { pointsApi, type PointsSystemStatus } from '../services/points'
import { Settings, Save, AlertTriangle, CheckCircle, Calendar, Coins, Key, ExternalLink, Bot } from 'lucide-react'
import { Button, EmptyState, Input, Spinner } from '../components/ui'
import { getErrorMessage } from '../services/api'

const AI_MODEL_SETTING_KEY = 'ai.copilot_model'

// Curated to models actually reachable through hermes's built-in "deepseek"
// provider (see app/services/ai_client.py) — the only provider currently
// wired with a working API key.
const AI_MODEL_OPTIONS = [
  { provider: 'deepseek', model: 'deepseek/deepseek-v4-flash', label: 'DeepSeek V4 Flash (fast, default)' },
  { provider: 'deepseek', model: 'deepseek/deepseek-chat', label: 'DeepSeek Chat' },
  { provider: 'deepseek', model: 'deepseek/deepseek-reasoner', label: 'DeepSeek Reasoner (slower, shows reasoning)' },
]

const AdminSettings: React.FC = () => {
  const { user } = useAuth()
  // Note: removed settings state as it was only used to extract required_days
  const [requiredDays, setRequiredDays] = useState<number>(180)
  const [pointsStatus, setPointsStatus] = useState<PointsSystemStatus | null>(null)
  const [aiModel, setAiModel] = useState<string>(AI_MODEL_OPTIONS[0].model)
  const [copilotMode, setCopilotMode] = useState<'agent' | 'direct'>('agent')
  const [savingAiModel, setSavingAiModel] = useState(false)
  const [savingCopilotMode, setSavingCopilotMode] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [togglingPoints, setTogglingPoints] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // No synchronous setState here: this runs from the mount effect, and the
  // set-state-in-effect lint rule requires state updates to happen inside the
  // promise callbacks. `loading` starts true; user-triggered reloads set the
  // spinner/error state in their own handlers before calling this.
  const loadSettings = () =>
    settingsApi
      .getGroupedSettings()
      .then(groupedSettings => {
        // Load attendance settings, then points system status
        setRequiredDays(groupedSettings.attendance.required_days_of_instruction)
        return pointsApi.getSystemStatus()
      })
      .then(pointsSystemStatus => {
        setPointsStatus(pointsSystemStatus)
        return settingsApi.getSetting(AI_MODEL_SETTING_KEY).catch(() => null)
      })
      .then(aiModelSetting => {
        if (aiModelSetting) {
          try {
            const parsed = JSON.parse(aiModelSetting.setting_value)
            if (parsed.model) setAiModel(parsed.model)
            if (parsed.mode === 'agent' || parsed.mode === 'direct') setCopilotMode(parsed.mode)
          } catch {
            // leave defaults
          }
        }
      })
      .catch(err => {
        setError(`Failed to load settings: ${getErrorMessage(err, 'Unknown error')}`)
      })
      .finally(() => {
        setLoading(false)
      })

  const saveRequiredDays = async () => {
    if (requiredDays < 1 || requiredDays > 365) {
      setError('Required days must be between 1 and 365')
      return
    }

    try {
      setSaving(true)
      setError(null)
      setSuccessMessage(null)

      await settingsApi.updateRequiredDaysOfInstruction(requiredDays)
      setSuccessMessage('Required days of instruction updated successfully!')

      // Reload settings to get the updated values
      setLoading(true)
      await loadSettings()
    } catch (err) {
      setError(`Failed to update setting: ${getErrorMessage(err, 'Unknown error')}`)
    } finally {
      setSaving(false)
    }
  }

  const saveAiModel = async (model: string) => {
    const option = AI_MODEL_OPTIONS.find((o) => o.model === model)
    if (!option) return
    try {
      setSavingAiModel(true)
      setError(null)
      setSuccessMessage(null)
      await settingsApi.upsertSetting(
        AI_MODEL_SETTING_KEY,
        JSON.stringify({ provider: option.provider, model: option.model, mode: copilotMode }),
        'json',
        'Model + mode used by the Copilot, AI Tutor, weekly planner, and auto-grading'
      )
      setAiModel(model)
      setSuccessMessage('AI copilot model updated successfully!')
    } catch (err) {
      setError(`Failed to update AI model: ${getErrorMessage(err, 'Unknown error')}`)
    } finally {
      setSavingAiModel(false)
    }
  }

  const saveCopilotMode = async (mode: 'agent' | 'direct') => {
    const option = AI_MODEL_OPTIONS.find((o) => o.model === aiModel) || AI_MODEL_OPTIONS[0]
    try {
      setSavingCopilotMode(true)
      setError(null)
      setSuccessMessage(null)
      await settingsApi.upsertSetting(
        AI_MODEL_SETTING_KEY,
        JSON.stringify({ provider: option.provider, model: aiModel, mode }),
        'json',
        'Model + mode used by the Copilot, AI Tutor, weekly planner, and auto-grading'
      )
      setCopilotMode(mode)
      setSuccessMessage('Copilot mode updated successfully!')
    } catch (err) {
      setError(`Failed to update copilot mode: ${getErrorMessage(err, 'Unknown error')}`)
    } finally {
      setSavingCopilotMode(false)
    }
  }

  const togglePointsSystem = async () => {
    try {
      setTogglingPoints(true)
      setError(null)
      setSuccessMessage(null)

      const result = await pointsApi.toggleSystem()
      setSuccessMessage(`Points system ${result.enabled ? 'enabled' : 'disabled'} successfully!`)

      // Reload settings to get the updated status
      setLoading(true)
      await loadSettings()
    } catch (err) {
      setError(`Failed to toggle points system: ${getErrorMessage(err, 'Unknown error')}`)
    } finally {
      setTogglingPoints(false)
    }
  }

  useEffect(() => {
    loadSettings()
  }, [])

  // Check if user is admin (after hooks so hook order stays stable)
  if (user?.role !== 'admin') {
    return (
      <div className="flex items-center justify-center py-24 text-center">
        <div>
          <AlertTriangle size={40} className="text-neg-fg mx-auto mb-3" />
          <h2 className="text-[18px] font-semibold text-ink">Access Denied</h2>
          <p className="text-[13px] text-muted mt-1">Only administrators can access system settings.</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-[13px] text-muted">
        <Spinner size="sm" />
        Loading settings...
      </div>
    )
  }

  // Load failed before any data arrived: show a retryable empty state rather
  // than a form of defaults that could silently overwrite real settings.
  if (error && !pointsStatus) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Couldn't load settings"
        subtext={error}
        action={
          <Button
            variant="secondary"
            onClick={() => {
              setLoading(true)
              setError(null)
              loadSettings()
            }}
          >
            Try Again
          </Button>
        }
      />
    )
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <p className="text-[11px] font-semibold text-faint uppercase tracking-[.06em] mb-0.5">Admin</p>
        <h1 className="text-[26px] font-semibold text-ink tracking-[-0.02em]">System Settings</h1>
        <p className="mt-1 text-[13px] text-muted">
          Configure system-wide settings that affect how OurSchool operates.
        </p>
      </div>

      {/* Error Message */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-card text-[13px] text-neg-fg bg-neg-bg border border-neg-fg/20">
          <AlertTriangle className="h-4 w-4 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Success Message */}
      {successMessage && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-card text-[13px] text-pos-fg bg-pos-bg border border-pos-fg/20">
          <CheckCircle className="h-4 w-4 flex-shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Attendance Settings */}
      <div className="bg-panel border border-line rounded-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Calendar className="h-4 w-4 text-faint" />
          <h2 className="text-[15px] font-semibold text-ink">Attendance Settings</h2>
        </div>

        <div className="space-y-4">
          <div>
            <label htmlFor="required-days" className="block text-[12px] font-semibold text-muted uppercase tracking-wide mb-1.5">
              Required Days of Instruction per Academic Year
            </label>
            <p className="text-[13px] text-muted mb-3">
              This value is used to calculate attendance percentages. Most jurisdictions require between 160-200 instructional days per year.
            </p>
            <div className="flex items-center gap-3">
              <Input
                id="required-days"
                type="number"
                min="1"
                max="365"
                value={requiredDays}
                onChange={(e) => setRequiredDays(parseInt(e.target.value) || 180)}
                fullWidth={false}
                className="w-28"
              />
              <span className="text-[13px] text-muted">days</span>
              <Button
                onClick={saveRequiredDays}
                loading={saving}
                icon={<Save className="h-4 w-4" />}
              >
                {saving ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>

          {/* About Attendance Calculations */}
          <div className="bg-panel-2 border border-line rounded-card p-4 mt-4">
            <h3 className="text-[13px] font-semibold text-ink mb-2">About Attendance Calculations</h3>
            <p className="text-[13px] text-muted">
              Attendance percentages are calculated as: (Present Days + Late Days + Excused Days) ÷ Required Days of Instruction × 100%
            </p>
            <p className="text-[13px] text-muted mt-1">
              This ensures compliance with educational requirements regardless of your actual term dates or calendar structure.
            </p>
          </div>
        </div>
      </div>

      {/* AI Copilot Settings */}
      <div className="bg-panel border border-line rounded-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Bot className="h-4 w-4 text-faint" />
          <h2 className="text-[15px] font-semibold text-ink">AI Copilot</h2>
        </div>

        <div className="space-y-4">
          <div>
            <label htmlFor="ai-model" className="block text-[12px] font-semibold text-muted uppercase tracking-wide mb-1.5">
              Copilot / Teacher Model
            </label>
            <p className="text-[13px] text-muted mb-3">
              The model used everywhere the AI acts as teacher: the AI Tutor chat, the weekly
              assignment planner, and auto-grading of AI-generated work.
            </p>
            <div className="flex items-center gap-3">
              <select
                id="ai-model"
                value={aiModel}
                onChange={(e) => saveAiModel(e.target.value)}
                disabled={savingAiModel}
                className="h-9 px-3 rounded-field border border-line bg-panel text-[13px] text-ink min-w-[320px]"
              >
                {AI_MODEL_OPTIONS.map((o) => (
                  <option key={o.model} value={o.model}>
                    {o.label}
                  </option>
                ))}
              </select>
              {savingAiModel && <Spinner size="sm" />}
            </div>
          </div>

          <div>
            <label className="block text-[12px] font-semibold text-muted uppercase tracking-wide mb-1.5">
              Copilot Mode
            </label>
            <p className="text-[13px] text-muted mb-3">
              How the Copilot chat (for both you and Jalayna) answers. Doesn't affect the AI Tutor,
              weekly planner, or auto-grading — those always use the model above directly.
            </p>
            <div className="flex flex-col gap-2">
              <label className="flex items-start gap-3 p-3 rounded-field border border-line cursor-pointer has-[:checked]:border-accent has-[:checked]:bg-accent/5">
                <input
                  type="radio"
                  name="copilot-mode"
                  checked={copilotMode === 'agent'}
                  onChange={() => saveCopilotMode('agent')}
                  disabled={savingCopilotMode}
                  className="mt-0.5"
                />
                <span>
                  <span className="block text-[13px] font-semibold text-ink">Agent (Recommended)</span>
                  <span className="block text-[12.5px] text-muted">
                    The sovereign hermes agent — real access to your school data (grades, attendance,
                    DeepTutor mastery) via tools, persistent memory across chats, and can propose real
                    changes for you to approve.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-3 p-3 rounded-field border border-line cursor-pointer has-[:checked]:border-accent has-[:checked]:bg-accent/5">
                <input
                  type="radio"
                  name="copilot-mode"
                  checked={copilotMode === 'direct'}
                  onChange={() => saveCopilotMode('direct')}
                  disabled={savingCopilotMode}
                  className="mt-0.5"
                />
                <span>
                  <span className="block text-[13px] font-semibold text-ink">Direct LLM</span>
                  <span className="block text-[12.5px] text-muted">
                    Plain chat with the model above — no tools, no memory, no proposals. Faster, but
                    it can't see your real data or take any action.
                  </span>
                </span>
              </label>
              {savingCopilotMode && (
                <div className="flex items-center gap-2 text-[12px] text-muted">
                  <Spinner size="sm" /> Saving...
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Points System Settings */}
      <div className="bg-panel border border-line rounded-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Coins className="h-4 w-4 text-faint" />
          <h2 className="text-[15px] font-semibold text-ink">Points System</h2>
        </div>

        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between gap-6">
              <div>
                <h3 className="text-[13.5px] font-semibold text-ink mb-1">
                  Enable Points System
                </h3>
                <p className="text-[13px] text-muted">
                  Control whether the gamification points system is active for students. When disabled, the Points Management section will be hidden from the Admin Center.
                </p>
              </div>
              <div className="flex items-center gap-4 flex-shrink-0">
                <div className="text-right">
                  <p className="text-[12px] text-faint">Status</p>
                  <p className={`text-[13px] font-semibold ${pointsStatus?.enabled ? 'text-pos-fg' : 'text-neg-fg'}`}>
                    {pointsStatus?.enabled ? 'Enabled' : 'Disabled'}
                  </p>
                </div>
                {pointsStatus?.can_toggle && (
                  <Button
                    variant={pointsStatus?.enabled ? 'danger' : 'success'}
                    onClick={togglePointsSystem}
                    loading={togglingPoints}
                    icon={<Settings className="h-4 w-4" />}
                  >
                    {togglingPoints
                      ? (pointsStatus?.enabled ? 'Disabling...' : 'Enabling...')
                      : `${pointsStatus?.enabled ? 'Disable' : 'Enable'} System`}
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* API Integration Settings */}
      <div className="bg-panel border border-line rounded-card p-6">
        <div className="flex items-center gap-2 mb-4">
          <Key className="h-4 w-4 text-faint" />
          <h2 className="text-[15px] font-semibold text-ink">API Integration</h2>
        </div>

        <div className="space-y-4">
          <div>
            <h3 className="text-[13.5px] font-semibold text-ink mb-2">
              External System Access
            </h3>
            <p className="text-[13px] text-muted mb-4">
              Allow external applications to access OurSchool's API using secure API keys. This enables integrations with learning platforms, behavior tracking tools, and other educational software.
            </p>

            <div className="bg-warn-soft border border-warn-line rounded-card p-4 mb-4">
              <div className="flex items-start">
                <AlertTriangle className="h-5 w-5 text-warn mr-2 mt-0.5 flex-shrink-0" />
                <div>
                  <h4 className="text-[13px] font-semibold text-warn">Security Notice</h4>
                  <p className="text-[13px] text-warn mt-1">
                    API keys provide direct access to student data and system functions. Only create keys for trusted applications and review permissions carefully.
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-6">
              <div>
                <h4 className="text-[13.5px] font-semibold text-ink">Manage API Keys</h4>
                <p className="text-[13px] text-muted">Create and manage API keys for external integrations</p>
              </div>
              <Button
                onClick={() => window.open('/admin/api-keys', '_blank')}
                icon={<Key className="h-4 w-4" />}
                className="flex-shrink-0"
              >
                Manage API Keys
                <ExternalLink className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AdminSettings
