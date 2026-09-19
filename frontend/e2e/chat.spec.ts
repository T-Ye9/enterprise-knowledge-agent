import { test, expect } from '@playwright/test'
import path from 'node:path'
import { writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

test('真实上传 → 检索与来源 → 连续追问 → calculator → 新建会话', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => {
    const observed = window as Window & { sseBodies: string[] }
    observed.sseBodies = []
    const original = window.fetch.bind(window)
    window.fetch = async (...args) => {
      const response = await original(...args)
      if (String(args[0]).endsWith('/chat/stream') && response.ok) {
        const body = response.body!
        const getReader = body.getReader.bind(body)
        body.getReader = () => {
          const reader = getReader()
          const read = reader.read.bind(reader)
          const decoder = new TextDecoder()
          let text = ''
          let recorded = false
          reader.read = async () => {
            const chunk = await read()
            text += decoder.decode(chunk.value, { stream: !chunk.done })
            if (!recorded && /event: done\ndata: .*\n\n/.test(text)) {
              observed.sseBodies.push(text); recorded = true
            }
            return chunk
          }
          return reader
        }
      }
      return response
    }
  })
  await page.goto('/')
  await expect(page.getByText('服务已连接', { exact: true })).toBeVisible()
  const uploaded = page.waitForResponse(response => response.url().endsWith('/documents') && response.request().method() === 'POST')
  const project = `Project Cedar 制度编号${Date.now()}`
  const fixture = path.resolve(`../tmp/pdfs/streaming-${Date.now()}.pdf`)
  const python = path.resolve(process.platform === 'win32' ? '../.venv/Scripts/python.exe' : '../.venv/bin/python')
  execFileSync(python, ['../samples/create_web_demo_pdf.py', '--output', fixture, '--project', project])
  await page.getByLabel('上传 PDF', { exact: true }).setInputFiles(fixture)
  await expect(page.getByText('正在解析并入库…', { exact: true })).toBeVisible()
  const uploadResponse = await uploaded
  expect(uploadResponse.status()).toBe(201)
  const document = (await uploadResponse.json()).document
  await expect(page.getByText(/已入库：/)).toBeVisible()

  let streamCount = 0
  async function send(question: string) {
    await page.getByLabel('输入问题').fill(question)
    const response = page.waitForResponse(r => r.url().endsWith('/chat/stream') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.locator('.loading')).toBeVisible()
    await expect(page.getByRole('button', { name: '发送问题' })).toBeDisabled()
    const result = await response
    expect(result.status()).toBe(200)
    expect(result.headers()['content-type']).toContain('text/event-stream')
    await page.waitForFunction(count => (window as Window & { sseBodies: string[] }).sseBodies.length > count, streamCount)
    const text = await page.evaluate(index => (window as Window & { sseBodies: string[] }).sseBodies[index], streamCount++)
    const events = text.split('\n\n').filter(frame => frame.startsWith('event:')).map(frame => {
      const lines = frame.split('\n'); return { event: lines[0].slice(7), data: JSON.parse(lines[1].slice(6)) }
    })
    expect(events.at(-1)?.event).toBe('done')
    expect(events.filter(e => e.event === 'delta').length).toBeGreaterThan(1)
    const body = events.at(-1)!.data
    await expect(page.locator('.loading')).toHaveCount(0)
    return { body, request: result.request().postDataJSON() }
  }

  const first = await send(`${project} 每位员工每月的健康补贴是多少元？`)
  expect(first.body.answer).toContain('731')
  expect(first.body.sources).toContainEqual({ document, page: 1 })
  await expect(page.locator('.source-chip').filter({ hasText: document }).first()).toContainText('第 1 页')
  const second = await send('那最晚什么时候提交材料？')
  expect(second.request.session_id).toBe(first.body.session_id)
  expect(second.body.sources).toContainEqual({ document, page: 1 })
  expect(second.body.answer).toMatch(/5|五/)
  const third = await send('帮我计算 123 * 456')
  expect(third.request.session_id).toBe(first.body.session_id)
  expect(third.body.answer.replaceAll(',', '')).toContain('56088')
  expect(third.body.sources).toEqual([])
  await page.screenshot({ path: 'test-results/chat-desktop.png', fullPage: true })
  await page.getByRole('button', { name: '＋ 新建对话' }).click()
  await expect(page.getByTestId('message-assistant')).toHaveCount(0)
  const fresh = await send('你好，请介绍一下你自己。')
  expect(fresh.request.session_id).toBeUndefined()
  expect(fresh.body.session_id).not.toBe(first.body.session_id)
  expect(fresh.body.sources).toEqual([])
  expect(errors).toEqual([])
  writeFileSync('../samples/streaming_examples.json', JSON.stringify({ uploaded_document: document,
    conversation: [first.body, second.body, third.body], new_conversation: fresh.body }, null, 2), 'utf8')
})

test('API 错误可见、输入可重试、非法上传可见', async ({ page }) => {
  await page.goto('/')
  await page.route('**/chat/stream', route => route.fulfill({ status: 502, contentType: 'application/json', body: JSON.stringify({ detail: '验收：LLM 服务调用失败' }) }))
  await page.getByLabel('输入问题').fill('测试错误')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByRole('alert')).toContainText('验收：LLM 服务调用失败')
  await expect(page.getByLabel('输入问题')).toHaveValue('测试错误')
  await expect(page.getByRole('button', { name: '发送问题' })).toBeEnabled()
  await page.getByLabel('上传 PDF', { exact: true }).setInputFiles({ name: 'wrong.txt', mimeType: 'text/plain', buffer: Buffer.from('test') })
  await expect(page.getByRole('alert')).toContainText('请选择非空 PDF')
})

test('手机布局无横向溢出', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '企业知识，随问随答。' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: 'test-results/chat-mobile.png', fullPage: true })
})
