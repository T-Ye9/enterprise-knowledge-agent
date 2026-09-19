export type Source = { document: string; page: number }
export type ChatReply = { answer: string; session_id: string; sources: Source[] }
export type UploadReply = { document: string; pages: number; chunks_saved: number }
export type StreamEvent =
  | { event: 'session'; data: { session_id: string } }
  | { event: 'reset'; data: Record<string, never> }
  | { event: 'delta'; data: { text: string } }
  | { event: 'tool_start'; data: { name: string; arguments: string } }
  | { event: 'tool_end'; data: { name: string } }
  | { event: 'done'; data: ChatReply }
  | { event: 'error'; data: { message: string; status: number } }

const API_URL = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 180_000)
  try {
    const response = await fetch(`${API_URL}${path}`, { ...options, signal: controller.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`)
    }
    if (response.status === 204) return undefined as T
    try { return await response.json() as T }
    catch (error) {
      if (error instanceof SyntaxError) throw new Error('服务返回的数据格式无效，请重试。')
      throw error
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('请求超时，请稍后重试。')
    if (error instanceof TypeError) throw new Error('无法连接服务，请确认后端已启动。')
    throw error
  } finally { window.clearTimeout(timeout) }
}

export const health = () => request<{ status: string }>('/health')
export const chat = (message: string, sessionId?: string) => request<ChatReply>('/chat', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, ...(sessionId ? { session_id: sessionId } : {}) }),
})

export async function streamChat(message: string, sessionId: string | undefined, onEvent: (event: StreamEvent) => void): Promise<void> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 180_000)
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
  try {
    const response = await fetch(`${API_URL}/chat/stream`, { method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message, ...(sessionId ? { session_id: sessionId } : {}) }), signal: controller.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`)
    }
    if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new Error('服务没有返回有效的事件流。')
    reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finished = false
    while (!finished) {
      const { value, done } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      // 一次网络读取可能包含半条事件、多个事件，甚至半个中文字符。
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const lines = frame.split('\n')
        const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim()
        const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
        if (!event || !data) continue
        let item: StreamEvent
        try { item = { event, data: JSON.parse(data) } as StreamEvent }
        catch { throw new Error('响应流的数据格式无效，请重试或新建对话。') }
        if ((item.event === 'delta' && typeof item.data?.text !== 'string') ||
            (item.event === 'done' && (typeof item.data?.answer !== 'string' || typeof item.data?.session_id !== 'string' || !Array.isArray(item.data?.sources)))) {
          throw new Error('响应流的数据结构无效，请重试或新建对话。')
        }
        if (item.event === 'error') throw new Error(item.data.message)
        onEvent(item)
        if (item.event === 'done') { finished = true; break }
      }
      if (done && !finished) throw new Error('响应流意外中断，未收到完成事件，请重试或新建对话。')
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('请求超时，请稍后重试或新建对话。')
    if (error instanceof TypeError) throw new Error('无法连接服务，或响应流已断开。')
    throw error
  } finally {
    await reader?.cancel().catch(() => undefined)
    controller.abort()
    window.clearTimeout(timeout)
  }
}
export const deleteSession = (id: string) => request<void>(`/sessions/${id}`, { method: 'DELETE' })
export const uploadDocument = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return request<UploadReply>('/documents', { method: 'POST', body: form })
}
