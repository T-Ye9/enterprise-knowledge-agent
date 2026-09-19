import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { streamChat, deleteSession, health, uploadDocument } from './api'
import type { Source } from './api'

type Message = { role: 'user' | 'assistant'; text: string; sources?: Source[] }
const suggestions = ['出差回来后多久提交报销？', '帮我计算 123 * 456', '你好，请介绍一下你自己。']
const uploadsEnabled = import.meta.env.VITE_ALLOW_DOCUMENT_UPLOAD !== 'false'

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('正在处理…')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [uploadStatus, setUploadStatus] = useState('')
  const [online, setOnline] = useState<boolean | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const blocked = busy || uploading

  useEffect(() => { let active = true; health().then(() => { if (active) setOnline(true) }).catch(() => { if (active) setOnline(false) }); return () => { active = false } }, [])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, busy])

  async function send(event: FormEvent) {
    event.preventDefault()
    const question = input.trim()
    if (!question || blocked) return
    setError(''); setBusy(true); setInput(''); setProgress('正在处理…')
    setMessages(previous => [...previous, { role: 'user', text: question }, { role: 'assistant', text: '' }])
    try {
      await streamChat(question, sessionId, event => {
        if (event.event === 'session') { setSessionId(event.data.session_id); setOnline(true) }
        if (event.event === 'tool_start') setProgress(`正在使用 ${event.data.name}…`)
        if (event.event === 'tool_end' || event.event === 'reset') setProgress('正在处理…')
        if (event.event === 'delta' || event.event === 'reset' || event.event === 'done') {
          setMessages(previous => {
            const last = previous[previous.length - 1]
            const updated: Message = event.event === 'done'
              ? { role: 'assistant', text: event.data.answer, sources: event.data.sources }
              : { ...last, text: event.event === 'reset' ? '' : last.text + event.data.text, sources: [] }
            return [...previous.slice(0, -1), updated]
          })
        }
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : '请求失败，请重试。')
      setInput(question)
      // 后端回滚了失败轮，页面也移除失败的提问，便于重试。
      setMessages(previous => previous.slice(0, -2))
    } finally { setBusy(false) }
  }

  async function reset() {
    if (blocked) return
    setBusy(true); setError('')
    try {
      if (sessionId) {
        try { await deleteSession(sessionId) }
        catch (err) { setError(`旧会话清理失败：${err instanceof Error ? err.message : '服务不可用'}。已开始新对话。`) }
      }
      // 即使旧 ID 因服务重启而失效，也可以建立全新会话。
      setSessionId(undefined); setMessages([]); setInput('')
    } finally { setBusy(false) }
  }

  async function upload(file?: File) {
    if (!file || blocked) return
    setError(''); setUploadStatus('')
    if (!file.name.toLowerCase().endsWith('.pdf') || file.size > 10 * 1024 * 1024 || file.size === 0) {
      setError('请选择非空 PDF，文件大小不超过 10 MB。'); return
    }
    setUploading(true)
    try {
      const result = await uploadDocument(file)
      setUploadStatus(`已入库：${result.document} · ${result.pages} 页 · ${result.chunks_saved} 个片段`)
    } catch (err) { setError(err instanceof Error ? err.message : '上传失败。') }
    finally { setUploading(false) }
  }

  return <div className="workspace">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Enterprise Knowledge Agent 首页"><span className="brand-mark">K</span><span>Knowledge Agent<small>企业知识助手</small></span></a>
      <button className="new-chat" onClick={reset} disabled={blocked}>＋ 新建对话</button>
      <div className="sidebar-section"><p className="eyebrow">知识库</p><h2>让文档成为答案</h2><p>{uploadsEnabled ? '上传企业 PDF，直接提问。' : '基于公开示例文档，直接提问。'}回答附带可核对的文件名与页码。</p>
        {uploadsEnabled && <>
        <label className={`upload-button ${blocked ? 'disabled' : ''}`}>
          {uploading ? '正在解析并入库…' : '↑ 上传 PDF'}
          <input aria-label="上传 PDF" type="file" accept=".pdf,application/pdf" disabled={blocked} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; void upload(file) }} />
        </label>
        <small className="hint">最多 10 MB / 100 页 · 文本型 PDF</small>
        </>}
        {uploadStatus && <p className="upload-result" role="status">{uploadStatus}</p>}
      </div>
      <div className="sidebar-footer"><span className={`status-dot ${online === true ? 'online' : ''}`} /><span>{online === null ? '正在检查服务' : online ? '服务已连接' : '服务未连接'}</span><p>PDF 检索 · 工具计算 · 连续对话</p></div>
    </aside>
    <main className="main">
      <header className="topbar"><div><p className="eyebrow">ENTERPRISE KNOWLEDGE AGENT</p><span>有依据的回答，从这里开始。</span></div><span className="session-tag">{sessionId ? `会话 ${sessionId.slice(0, 8)}` : '新会话'}</span></header>
      <section className="conversation" aria-label="聊天记录" aria-live="polite">
        {messages.length === 0 && <div className="welcome"><div className="welcome-icon">K</div><p className="eyebrow">YOUR KNOWLEDGE, CONNECTED</p><h1>企业知识，随问随答。</h1><p>查制度、问文档、做计算。<br />可以接着追问，文档答案会展示来源。</p><div className="suggestions">{suggestions.map(question => <button key={question} onClick={() => setInput(question)} disabled={blocked}>{question}<span>↗</span></button>)}</div></div>}
        {messages.map((message, index) => <article className={`message ${message.role}`} key={index} data-testid={`message-${message.role}`}><div className="avatar">{message.role === 'user' ? '你' : 'K'}</div><div className="message-body"><p className="message-label">{message.role === 'user' ? '你' : 'Knowledge Agent'}</p><div className="answer">{message.text}</div>{!!message.sources?.length && <div className="sources"><p>参考来源</p>{message.sources.map(source => <span className="source-chip" key={`${source.document}:${source.page}`}>{source.document}<b>第 {source.page} 页</b></span>)}</div>}</div></article>)}
        {busy && <div className="loading" role="status"><span className="spinner" />{progress}</div>}
        <div ref={bottom} />
      </section>
      <div className="composer-area">{error && <div className="error" role="alert">{error} <button onClick={() => setError('')} aria-label="关闭错误">×</button></div>}<form onSubmit={send} className="composer"><label className="sr-only" htmlFor="question">输入问题</label><textarea id="question" placeholder="输入问题，或接着上一轮追问…" value={input} disabled={blocked} rows={2} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (input.trim() && !blocked) event.currentTarget.form?.requestSubmit() } }} /><button className="send" type="submit" disabled={blocked || !input.trim()} aria-label="发送问题">{busy ? '等待中' : '发送 ↑'}</button></form><p className="composer-note">Enter 发送 · Shift + Enter 换行 · 新建对话清空上下文，不删除知识库</p></div>
    </main>
  </div>
}
