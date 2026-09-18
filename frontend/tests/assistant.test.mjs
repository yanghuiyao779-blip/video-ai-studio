import test from 'node:test'
import assert from 'node:assert/strict'
import { mediaCandidates } from '../src/assistant/urls.js'
import { streamRun, terminal } from '../src/assistant/api.js'
import { request, getToken, setToken } from '../src/api.js'

const store = new Map()
globalThis.sessionStorage = {
  getItem: key => store.get(key) || null,
  setItem: (key, value) => store.set(key, value),
  removeItem: key => store.delete(key),
}
globalThis.window = new EventTarget()

const media = [
  'https://www.bilibili.com/video/BV123',
  'https://b23.tv/xyz',
  'https://www.youtube.com/watch?v=test',
  'https://youtu.be/abc',
  'https://www.youtube.com/shorts/abc',
  'https://v.douyin.com/aBc/',
  'https://www.douyin.com/video/123',
  'https://www.douyin.com/jingxuan?modal_id=123',
  'https://cdn.example.com/file.MP4?signature=abc',
]
for (const url of media) {
  test(`media URL recognized: ${url}`, () => assert.deepEqual(mediaCandidates(url), [url]))
}
const other = [
  'https://www.bilibili.com/',
  'https://www.youtube.com/@channel',
  'https://www.douyin.com/user/self?modal_id=123',
  'https://www.douyin.com/user/MS4foo',
  'https://docs.example.com/intro',
  'https://notbilibili.com/video/123',
  'https://bilibili.com.evil.example/video/123',
  'https://user:password@youtu.be/id',
  'javascript:alert(1)',
]
for (const url of other) {
  test(`not auto-downloaded: ${url}`, () => assert.deepEqual(mediaCandidates(url), []))
}
test('share text strips punctuation and deduplicates links', () => {
  const url = media[0]
  assert.deepEqual(mediaCandidates(`请总结 ${url}。\n${url}`), [url])
})
function streaming(text, bytesPerChunk = 1) {
  const data = new TextEncoder().encode(text)
  return new Response(new ReadableStream({
    start(controller) {
      for (let i = 0; i < data.length; i += bytesPerChunk) controller.enqueue(data.slice(i, i + bytesPerChunk))
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } })
}
test('SSE preserves UTF-8 across byte splits, CRLF, heartbeat and revisions', async () => {
  setToken('synthetic-test-token')
  const snapshots = [{ revision: 1, content: '你好' }, { revision: 2, content: '你好 WORLD' }]
  let observed
  const text = ': keepalive\r\n\r\n' + snapshots.map(s => `event: snapshot\r\ndata: ${JSON.stringify(s)}\r\n\r\n`).join('')
  const original = globalThis.fetch
  try {
    globalThis.fetch = async (url, opts) => { observed = { url, opts }; return streaming(text) }
    const got = []
    await streamRun('run/id', value => got.push(value), new AbortController().signal)
    assert.deepEqual(got, snapshots)
    assert.ok(observed.url.endsWith('run%2Fid/stream'))
    assert.equal(observed.opts.headers.Authorization, 'Bearer synthetic-test-token')
    assert.ok(!observed.url.includes('token'))
  } finally { globalThis.fetch = original }
})
test('SSE rejects server access errors and malformed snapshots', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => streaming('event: error\ndata: {"message":"Access revoked"}\n\n')
    await assert.rejects(streamRun('x', () => {}), /Access revoked/)
    globalThis.fetch = async () => streaming('event: snapshot\ndata: malformed\n\n')
    await assert.rejects(streamRun('x', () => {}), SyntaxError)
  } finally { globalThis.fetch = original }
})
test('401 clears session token and emits auth-expired', async () => {
  const original = globalThis.fetch
  let count = 0
  const listener = () => count++
  window.addEventListener('video-ai-auth-expired', listener)
  try {
    setToken('expired')
    globalThis.fetch = async () => new Response('{}', { status: 401 })
    await assert.rejects(streamRun('x', () => {}), /401/)
    assert.equal(getToken(), null)
    assert.equal(count, 1)
  } finally {
    globalThis.fetch = original
    window.removeEventListener('video-ai-auth-expired', listener)
  }
})
test('fetch abort is propagated without changing server run state', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => { throw new DOMException('Aborted', 'AbortError') }
    await assert.rejects(streamRun('x', () => {}, AbortSignal.abort()), { name: 'AbortError' })
  } finally { globalThis.fetch = original }
})
test('authenticated API wrapper preserves validation errors and 204', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response('{"detail":"Read only"}', { status: 403 })
    await assert.rejects(request('/api/test'), /Read only/)
    globalThis.fetch = async () => new Response(null, { status: 204 })
    assert.equal(await request('/api/test'), null)
  } finally { globalThis.fetch = original }
})
test('only terminal server statuses stop watching', () => {
  assert.equal(terminal('queued'), false)
  assert.equal(terminal('waiting'), false)
  assert.equal(terminal('running'), false)
  for (const status of ['completed', 'cancelled', 'failed']) assert.equal(terminal(status), true)
})
