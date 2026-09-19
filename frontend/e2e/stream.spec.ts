import { test, expect } from '@playwright/test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

test('完成事件前可见部分文字，跨网络分片和中文字符正确解析', async ({ page }) => {
  let completed = false
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Access-Control-Allow-Origin': new URL(process.env.E2E_BASE_URL || 'http://127.0.0.1:5173').origin })
    response.write('event: session\ndata: {"session_id":"00000000-0000-0000-0000-000000000001"}\n\n')
    const frame = Buffer.from('event: delta\ndata: {"text":"你好"}\n\n')
    const cut = frame.indexOf(Buffer.from('你')) + 1 // 故意拆开 UTF-8 汉字。
    response.write(frame.subarray(0, cut))
    setTimeout(() => response.write(frame.subarray(cut)), 150)
    setTimeout(() => response.write('event: delta\ndata: {"text":"，这是逐步生成的回答。"}\n\n'), 600)
    setTimeout(() => {
      completed = true
      response.end('event: done\ndata: {"answer":"你好，这是逐步生成的回答。","sources":[],"session_id":"00000000-0000-0000-0000-000000000001"}\n\n')
    }, 2000)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as AddressInfo).port
  try {
    await page.route('**/chat/stream', route => route.continue({ url: `http://127.0.0.1:${port}/chat/stream` }))
    await page.goto('/')
    await page.getByLabel('输入问题').fill('展示流式回答')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.getByTestId('message-assistant')).toContainText('你好')
    expect(completed).toBe(false)
    await expect(page.locator('.loading')).toBeVisible()
    await expect(page.getByRole('button', { name: '发送问题' })).toBeDisabled()
    await expect(page.getByTestId('message-assistant')).toContainText('你好，这是逐步生成的回答。')
    await expect(page.locator('.loading')).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
    await page.screenshot({ path: 'test-results/stream-complete.png', fullPage: true })
  } finally { await new Promise<void>(resolve => server.close(() => resolve())) }
})

for (const kind of ['error', 'eof'] as const) {
  test(`流式 ${kind} 清除部分消息并结束 loading`, async ({ page }) => {
    const body = 'event: session\ndata: {"session_id":"00000000-0000-0000-0000-000000000002"}\n\nevent: delta\ndata: {"text":"未完成的内容"}\n\n'
      + (kind === 'error' ? 'event: error\ndata: {"status":502,"message":"验收：模型流失败"}\n\n' : '')
    await page.route('**/chat/stream', route => route.fulfill({ status: 200, contentType: 'text/event-stream', body }))
    await page.goto('/')
    await page.getByLabel('输入问题').fill('测试中断')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.getByRole('alert')).toContainText(kind === 'error' ? '模型流失败' : '响应流意外中断')
    await expect(page.locator('.loading')).toHaveCount(0)
    await expect(page.getByTestId('message-assistant')).toHaveCount(0)
    await expect(page.getByLabel('输入问题')).toHaveValue('测试中断')
    await expect(page.getByRole('button', { name: '发送问题' })).toBeEnabled()
  })
}
