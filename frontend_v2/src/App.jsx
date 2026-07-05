import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function asJson(value) {
  return JSON.stringify(value ?? null, null, 2)
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result || '')
      resolve(result.includes(',') ? result.split(',')[1] : result)
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

function getAcceptedFileType(file) {
  if (!file) return 'application/octet-stream'
  const explicitType = String(file.type || '').trim().toLowerCase()
  if (['application/pdf', 'image/png', 'image/jpeg', 'image/jpg'].includes(explicitType)) {
    return explicitType === 'image/jpg' ? 'image/jpeg' : explicitType
  }

  const extension = String(file.name || '').toLowerCase().split('.').pop()
  if (extension === 'pdf') return 'application/pdf'
  if (extension === 'png') return 'image/png'
  if (['jpg', 'jpeg', 'jfif'].includes(extension)) return 'image/jpeg'
  return explicitType || 'application/octet-stream'
}

function JsonBlock({ title, value, compact = false }) {
  return (
    <section className={`json-card ${compact ? 'compact' : ''}`}>
      <div className="section-title">{title}</div>
      <pre>{asJson(value)}</pre>
    </section>
  )
}

function StatusPill({ status }) {
  if (!status) return null
  return <span className={`status-pill status-${String(status).toLowerCase()}`}>{status}</span>
}

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [authLoading, setAuthLoading] = useState(true)
  const [authError, setAuthError] = useState('')
  const [githubUser, setGithubUser] = useState(() => localStorage.getItem('mini_v2_user') || '')
  const [sessions, setSessions] = useState([])
  const [selectedSessionId, setSelectedSessionId] = useState(() => localStorage.getItem('mini_v2_session') || '')
  const [messages, setMessages] = useState([])
  const [messageText, setMessageText] = useState('')
  const [state, setState] = useState(null)
  const [lastResponse, setLastResponse] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [approvalResourceTypes, setApprovalResourceTypes] = useState('')
  const [approvalResourceIds, setApprovalResourceIds] = useState('')
  const [approvalIntakeId, setApprovalIntakeId] = useState('')
  const [approvalFile, setApprovalFile] = useState(null)
  const [lastUpload, setLastUpload] = useState(null)

  const chatEndRef = useRef(null)
  const approvalFileRef = useRef(null)

  const resetApprovalUploadForm = () => {
    setApprovalResourceTypes('')
    setApprovalResourceIds('')
    setApprovalIntakeId('')
    setApprovalFile(null)
    setLastUpload(null)
    if (approvalFileRef.current) approvalFileRef.current.value = ''
  }

  const headers = useMemo(() => ({
    'Content-Type': 'application/json',
    'X-GitHub-User': githubUser || 'default',
  }), [githubUser])

  // ─── GitHub OAuth ────────────────────────────────────────────────────────────
  useEffect(() => {
    const init = async () => {
      try {
        const params = new URLSearchParams(window.location.search)

        // OAuth callback: ?auth=success&github_user=xxx
        if (params.get('auth') === 'success' && params.get('github_user')) {
          const user = params.get('github_user')
          localStorage.setItem('mini_v2_user', user)
          setGithubUser(user)
          setIsAuthenticated(true)
          window.history.replaceState({}, '', window.location.pathname)
          return
        }

        // Auth error from callback
        if (params.get('auth_error')) {
          window.history.replaceState({}, '', window.location.pathname)
          setAuthError('GitHub authentication failed. Please try again.')
          return
        }

        // Returning user — validate with /auth/me
        const savedUser = localStorage.getItem('mini_v2_user')
        if (!savedUser || savedUser === 'default') return

        const resp = await fetch(`${API_BASE}/auth/me`, {
          headers: { 'X-GitHub-User': savedUser },
        })
        const auth = await resp.json()
        if (auth?.authenticated) {
          setGithubUser(savedUser)
          setIsAuthenticated(true)
        } else {
          localStorage.removeItem('mini_v2_user')
          setGithubUser('')
        }
      } catch {
        localStorage.removeItem('mini_v2_user')
        setGithubUser('')
      } finally {
        setAuthLoading(false)
      }
    }
    init()
  }, [])

  const logout = () => {
    localStorage.removeItem('mini_v2_user')
    localStorage.removeItem('mini_v2_session')
    setIsAuthenticated(false)
    setGithubUser('')
    setSessions([])
    setMessages([])
    setState(null)
    setSelectedSessionId('')
    resetApprovalUploadForm()
  }

  const loginUrl = `${API_BASE}/auth/github?return_to=${encodeURIComponent(window.location.origin)}`

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body instanceof FormData ? {} : headers),
        ...(options.headers || {}),
      },
    })
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`
      try {
        const data = await response.json()
        detail = data.detail || JSON.stringify(data)
      } catch {
        // keep default detail
      }
      throw new Error(detail)
    }
    if (response.status === 204) return null
    return response.json()
  }, [headers])

  const loadSessions = useCallback(async () => {
    const data = await request('/api/chats')
    setSessions(data.chats || [])
    return data.chats || []
  }, [request])

  const refreshMessages = useCallback(async (sessionId = selectedSessionId) => {
    if (!sessionId) {
      setMessages([])
      return
    }
    const data = await request(`/api/chats/${sessionId}/messages`)
    setMessages(Array.isArray(data) ? data : [])
  }, [request, selectedSessionId])

  const refreshState = useCallback(async (sessionId = selectedSessionId) => {
    if (!sessionId) {
      setState(null)
      return
    }
    const data = await request(`/api/debug/chats/${sessionId}/state`)
    setState(data)
  }, [request, selectedSessionId])

  const refreshAll = useCallback(async (sessionId = selectedSessionId) => {
    await Promise.all([
      loadSessions(),
      refreshMessages(sessionId),
      refreshState(sessionId),
    ])
  }, [loadSessions, refreshMessages, refreshState, selectedSessionId])

  useEffect(() => {
    if (selectedSessionId) localStorage.setItem('mini_v2_session', selectedSessionId)
  }, [selectedSessionId])

  useEffect(() => {
    loadSessions().catch((err) => setError(err.message))
  }, [loadSessions])

  useEffect(() => {
    if (!selectedSessionId) return
    refreshAll(selectedSessionId).catch((err) => setError(err.message))
  }, [selectedSessionId, refreshAll])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, lastResponse])

  const createSession = async () => {
    setError('')
    setLoading(true)
    try {
      const chat = await request('/api/chats', { method: 'POST', body: JSON.stringify({}) })
      setSelectedSessionId(chat.id)
      setLastResponse(chat)
      resetApprovalUploadForm()
      await refreshAll(chat.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const ensureSession = async () => {
    if (selectedSessionId) return selectedSessionId
    const chat = await request('/api/chats', { method: 'POST', body: JSON.stringify({}) })
    setSelectedSessionId(chat.id)
    setLastResponse(chat)
    await refreshAll(chat.id)
    return chat.id
  }

  const deleteSelectedSession = async () => {
    if (!selectedSessionId) return
    if (!window.confirm('Delete selected debug session?')) return
    setError('')
    setLoading(true)
    try {
      await request(`/api/chats/${selectedSessionId}`, { method: 'DELETE' })
      setSelectedSessionId('')
      setMessages([])
      setState(null)
      setLastResponse(null)
      await loadSessions()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const sendMessage = async () => {
    const text = messageText.trim()
    if (!text) return
    setError('')
    setLoading(true)
    try {
      let sessionId = selectedSessionId
      if (!sessionId) {
        const chat = await request('/api/chats', { method: 'POST', body: JSON.stringify({}) })
        sessionId = chat.id
        setSelectedSessionId(chat.id)
      }
      setMessageText('')
      const response = await request('/api/chat', {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, message: text }),
      })
      setLastResponse(response)
      await refreshAll(sessionId)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const sendApprovalUploadToAgent = async ({ upload, resourceTypes, sessionId }) => {
    const resourceIds = approvalResourceIds.split(',').map((item) => item.trim()).filter(Boolean)
    const payload = {
      resource_types: resourceTypes,
      resource_ids: resourceIds.length ? resourceIds : undefined,
      file_id: upload.file_id,
      file_name: upload.file_name,
      file_type: upload.file_type,
      intake_id: approvalIntakeId.trim() || undefined,
    }
    const message = [
      'I uploaded a data-owner approval document for the current create flow.',
      'Please call validate_data_owner_approval_document with this uploaded file and continue the flow.',
      JSON.stringify(payload, null, 2),
    ].join('\n')

    return request('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message }),
    })
  }

  const uploadApproval = async ({ sendToAgent = false } = {}) => {
    if (!approvalFile) {
      setError('Choose an approval PDF/image first.')
      return
    }
    setError('')
    setLoading(true)
    try {
      const sessionId = await ensureSession()
      const resourceTypes = approvalResourceTypes.split(',').map((item) => item.trim()).filter(Boolean)
      if (!resourceTypes.length) {
        throw new Error('Enter at least one resource type, for example glue_db.')
      }
      const fileContentBase64 = await fileToBase64(approvalFile)
      const fileType = getAcceptedFileType(approvalFile)
      const upload = await request('/api/data-owner-approval/upload', {
        method: 'POST',
        body: JSON.stringify({
          resource_types: resourceTypes,
          resource_ids: approvalResourceIds.split(',').map((item) => item.trim()).filter(Boolean),
          session_id: sessionId,
          intake_id: approvalIntakeId.trim() || undefined,
          file_name: approvalFile.name,
          file_type: fileType,
          file_content_base64: fileContentBase64,
        }),
      })
      setLastUpload(upload)
      setLastResponse(upload)

      if (sendToAgent) {
        const agent = await sendApprovalUploadToAgent({ upload, resourceTypes, sessionId })
        setLastResponse({ upload, agent })
      }
      await refreshAll(sessionId)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const sendLastUploadToAgent = async () => {
    if (!lastUpload?.file_id) {
      setError('Upload a file first.')
      return
    }
    setError('')
    setLoading(true)
    try {
      const sessionId = await ensureSession()
      const resourceTypes = (lastUpload.resource_types?.length ? lastUpload.resource_types : approvalResourceTypes.split(','))
        .map((item) => String(item).trim())
        .filter(Boolean)
      if (!resourceTypes.length) {
        throw new Error('Enter at least one resource type, for example glue_db.')
      }
      const agent = await sendApprovalUploadToAgent({ upload: lastUpload, resourceTypes, sessionId })
      setLastResponse({ upload: lastUpload, agent })
      await refreshAll(sessionId)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const activeResources = state?.session?.resources || []
  const sessionFields = state?.session_fields || {}
  const selectedSession = sessions.find((session) => session.id === selectedSessionId)
  const pendingApprovalTypes = state?.debug?.pending_approval?.resource_types || []
  const pendingApprovalTypesText = pendingApprovalTypes.join(',')
  const pendingApprovalTargets = state?.debug?.pending_approval?.pending_targets || state?.debug?.pending_approval?.blocked || []
  const pendingApprovalIds = pendingApprovalTargets.map((target) => target.resource_id).filter(Boolean)
  const pendingApprovalIdsText = pendingApprovalIds.join(',')
  const pendingApprovalTargetsText = JSON.stringify(pendingApprovalTargets)

  useEffect(() => {
    if (pendingApprovalTypes.length && !approvalResourceTypes.trim()) {
      setApprovalResourceTypes(pendingApprovalTypes.join(','))
    }
    const currentIds = approvalResourceIds.split(',').map((item) => item.trim()).filter(Boolean)
    const hasStaleTarget = currentIds.some((id) => !pendingApprovalIds.includes(id))
    let selectedResourceId = currentIds[0]
    if (pendingApprovalIds.length && (!currentIds.length || hasStaleTarget)) {
      selectedResourceId = pendingApprovalIds[0]
      setApprovalResourceIds(selectedResourceId)
    }
    const selectedTarget = pendingApprovalTargets.find((target) => target.resource_id === selectedResourceId)
    if (selectedTarget?.intake_id && approvalIntakeId !== selectedTarget.intake_id) {
      setApprovalIntakeId(selectedTarget.intake_id)
    }
  }, [pendingApprovalTypesText, pendingApprovalIdsText, pendingApprovalTargetsText, approvalResourceTypes, approvalResourceIds, approvalIntakeId])

  // ─── Login screen ──────────────────────────────────────────────────────────
  if (authLoading) {
    return (
      <div className="login-screen">
        <div className="login-card">
          <div className="mini-badge">MiNi</div>
          <p>Loading...</p>
        </div>
      </div>
    )
  }

  if (!isAuthenticated) {
    return (
      <div className="login-screen">
        <div className="login-card">
          <div className="mini-badge">MiNi</div>
          <h1>Debug UI v2</h1>
          <p>Sign in with GitHub to test backend flows including PR creation.</p>
          {authError && <div className="error-banner">{authError}</div>}
          <a className="btn primary login-btn" href={loginUrl}>Sign in with GitHub</a>
        </div>
      </div>
    )
  }

  // ─── Main debug UI ─────────────────────────────────────────────────────────
  return (
    <div className="debug-shell">
      <aside className="sessions-panel panel">
        <div className="brand-row">
          <div>
            <div className="mini-badge">MiNi</div>
            <h1>Debug UI v2</h1>
          </div>
          <span className="live-dot">test</span>
        </div>

        <div className="auth-row">
          <span className="auth-user">{githubUser}</span>
          <button className="btn btn-sm" onClick={logout}>Logout</button>
        </div>

        <div className="button-row">
          <button className="btn primary" onClick={createSession} disabled={loading}>+ New</button>
          <button className="btn" onClick={() => refreshAll()} disabled={loading || !selectedSessionId}>Refresh</button>
          <button className="btn danger" onClick={deleteSelectedSession} disabled={loading || !selectedSessionId}>Delete</button>
        </div>

        <div className="section-title with-count">Sessions <span>{sessions.length}</span></div>
        <div className="session-list">
          {sessions.map((session) => (
            <button
              key={session.id}
              className={`session-item ${session.id === selectedSessionId ? 'active' : ''}`}
              onClick={() => {
                setSelectedSessionId(session.id)
                resetApprovalUploadForm()
              }}
            >
              <span className="session-title">{session.title || 'New Chat'}</span>
              <span className="session-meta">{session.message_count} msgs · {formatTime(session.updated_at)}</span>
              <span className="session-id">{session.id}</span>
            </button>
          ))}
          {!sessions.length && <div className="empty-state">No sessions yet.</div>}
        </div>
      </aside>

      <main className="chat-panel panel">
        <header className="chat-header">
          <div>
            <h2>{selectedSession?.title || 'Simple backend test chat'}</h2>
            <p>{selectedSessionId || 'No session selected'}</p>
          </div>
          <div className="resource-strip">
            {activeResources.map((resource) => (
              <span key={resource.resource_id} className="resource-chip">
                {resource.resource_id}<StatusPill status={resource.status} />
              </span>
            ))}
            {!activeResources.length && <span className="resource-chip muted">no resources</span>}
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <section className="messages-box">
          {messages.map((message) => (
            <div key={message.id} className={`message-row ${message.role}`}>
              <div className="message-bubble">
                <div className="message-role">{message.role}</div>
                <div className="message-content">{message.content}</div>
              </div>
            </div>
          ))}
          {!messages.length && (
            <div className="empty-chat">
              <strong>Start testing backend flow.</strong>
              <span>Try: “create glue db” or “create s3 bucket”.</span>
            </div>
          )}
          <div ref={chatEndRef} />
        </section>

        <section className="composer">
          <textarea
            value={messageText}
            onChange={(event) => setMessageText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                sendMessage()
              }
            }}
            placeholder="Type a backend test message..."
            disabled={loading}
          />
          <button className="btn primary send" onClick={sendMessage} disabled={loading || !messageText.trim()}>
            {loading ? 'Working…' : 'Send'}
          </button>
        </section>

        <section className="approval-card">
          <div className="section-title">Data owner approval upload</div>
          <div className="approval-grid">
            <label>
              Resource types
              <input className="input" value={approvalResourceTypes} onChange={(event) => setApprovalResourceTypes(event.target.value)} />
            </label>
            <label>
              Target resource IDs
              <input className="input" value={approvalResourceIds} onChange={(event) => setApprovalResourceIds(event.target.value)} placeholder="e.g. glue_db_0 or glue_db_0,glue_db_1" />
            </label>
            <label>
              Intake ID
              <input className="input" value={approvalIntakeId} onChange={(event) => setApprovalIntakeId(event.target.value)} placeholder="optional" />
            </label>
            <label className="file-picker">
              Approval image/PDF
              <input
                ref={approvalFileRef}
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,.jfif,application/pdf,image/png,image/jpeg,image/jpg"
                onChange={(event) => setApprovalFile(event.target.files?.[0] || null)}
              />
              <button type="button" className="btn file-select-btn" onClick={() => approvalFileRef.current?.click()} disabled={loading}>
                Choose PDF/image
              </button>
            </label>
          </div>
          {pendingApprovalTypes.length > 0 && (
            <div className="file-note">Pending approval for: {pendingApprovalTypes.join(', ')}</div>
          )}
          {pendingApprovalTargets.length > 0 && (
            <div className="file-note">
              Pending targets: {pendingApprovalTargets.map((target) => `${target.resource_id}${target.intake_id ? ` (${target.intake_id})` : ''}`).join(', ')}. Use comma-separated IDs if one document covers multiple targets.
            </div>
          )}
          {approvalFile && <div className="file-note">Selected: {approvalFile.name} ({getAcceptedFileType(approvalFile)})</div>}
          <div className="button-row">
            <button className="btn" onClick={() => uploadApproval()} disabled={loading || !approvalFile}>Upload only</button>
            <button className="btn primary" onClick={() => uploadApproval({ sendToAgent: true })} disabled={loading || !approvalFile}>Upload + send to agent</button>
            <button className="btn" onClick={sendLastUploadToAgent} disabled={loading || !lastUpload?.file_id}>Send last upload to agent</button>
          </div>
          {lastUpload?.file_id && <div className="file-note">Last file_id: <code>{lastUpload.file_id}</code></div>}
        </section>
      </main>

      <aside className="state-panel panel">
        <div className="state-header">
          <div>
            <h2>Backend State</h2>
            <p>Refreshes after each action</p>
          </div>
          <button className="btn" onClick={() => refreshAll()} disabled={loading || !selectedSessionId}>Refresh</button>
        </div>

        <div className="quick-state">
          <div><span>Route</span><strong>{sessionFields.__active_route || '—'}</strong></div>
          <div><span>Resources</span><strong>{activeResources.length}</strong></div>
          <div><span>Messages</span><strong>{state?.session?.message_count ?? messages.length}</strong></div>
        </div>

        <JsonBlock title="Debug helper state" value={state?.debug} compact />
        <JsonBlock title="Resources" value={activeResources} />
        <JsonBlock title="Session fields" value={sessionFields} />
        <JsonBlock title="Last API response" value={lastResponse} />
        <JsonBlock title="Full debug payload" value={state} />
      </aside>
    </div>
  )
}

export default App
