const TOKEN_KEY = 'video_ai_access_token'

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  else sessionStorage.removeItem(TOKEN_KEY)
}

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  let response
  try {
    response = await fetch(path, { ...options, headers })
  } catch {
    throw new Error('无法连接服务器，请检查网络或服务状态')
  }
  if (response.status === 401) {
    setToken(null)
    window.dispatchEvent(new Event('video-ai-auth-expired'))
  }
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail : message
    } catch {
      // Keep fallback message for non-JSON errors.
    }
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

function uploadRequest(formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/jobs/upload')
    const token = getToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onerror = () => reject(new Error('文件上传失败，请检查网络连接'))
    xhr.onload = () => {
      if (xhr.status === 401) {
        setToken(null)
        window.dispatchEvent(new Event('video-ai-auth-expired'))
      }
      let body = null
      try { body = JSON.parse(xhr.responseText || 'null') } catch { /* ignore */ }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(body?.detail || `上传失败（HTTP ${xhr.status}）`))
        return
      }
      resolve(body)
    }
    xhr.send(formData)
  })
}

export const api = {
  login: (username, password) => request('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  }),
  me: () => request('/api/auth/me'),
  changePassword: (payload) => request('/api/auth/password', { method: 'PUT', body: JSON.stringify(payload) }),
  health: () => request('/api/health'),
  jobs: () => request('/api/jobs'),
  previewVideo: (sourceUrl) => request('/api/jobs/preview', {
    method: 'POST',
    body: JSON.stringify({ source_url: sourceUrl }),
  }),
  createJob: (payload) => request('/api/jobs', { method: 'POST', body: JSON.stringify(payload) }),
  uploadJob: (formData, onProgress) => uploadRequest(formData, onProgress),
  getJob: (id) => request(`/api/jobs/${id}`),
  getJobResult: (id) => request(`/api/jobs/${id}/result`),
  updateTranscript: (id, segments) => request(`/api/jobs/${id}/transcript`, { method: 'PUT', body: JSON.stringify({ segments }) }),
  retryJob: (id) => request(`/api/jobs/${id}/retry`, { method: 'POST' }),
  cancelJob: (id) => request(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  resummarizeJob: (id, payload) => request(`/api/jobs/${id}/resummarize`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  deleteJob: (id) => request(`/api/jobs/${id}`, { method: 'DELETE' }),
  getLLM: () => request('/api/settings/llm'),
  saveLLM: (payload) => request('/api/settings/llm', { method: 'PUT', body: JSON.stringify(payload) }),
  testLLM: () => request('/api/settings/llm/test', { method: 'POST' }),
  getTaskDefaults: () => request('/api/settings/task-defaults'),
  saveTaskDefaults: (payload) => request('/api/settings/task-defaults', { method: 'PUT', body: JSON.stringify(payload) }),
  getStorage: () => request('/api/settings/storage'),
  cleanTemporaryStorage: () => request('/api/settings/storage/temporary', { method: 'DELETE' }),
  downloadArtifact: async (jobId, name) => {
    const token = getToken()
    const response = await fetch(`/api/jobs/${jobId}/artifacts/${name}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) throw new Error(`文件下载失败（HTTP ${response.status}）`)
    const blob = await response.blob()
    const disposition = response.headers.get('content-disposition') || ''
    const match = disposition.match(/filename="?([^";]+)"?/i)
    const filename = match?.[1] || `${jobId}-${name}`
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },
}
