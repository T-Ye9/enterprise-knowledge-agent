import { test, expect } from '@playwright/test'

for (const kind of ['network', 'http', 'json', 'schema', 'timeout'] as const) {
  test(`API ${kind} 故障可见且结束 loading`, async ({ page }) => {
    await page.route('**/health', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' }))
    if (kind === 'timeout') {
      // 只缩短现有 API 超时定时器，不等待真实 180 秒。
      await page.addInitScript(() => {
        const original = window.setTimeout.bind(window)
        window.setTimeout = ((handler: TimerHandler, delay?: number, ...args: unknown[]) => original(handler, delay === 180_000 ? 100 : delay, ...args)) as typeof window.setTimeout
      })
    }
    await page.route('**/chat/stream', async route => {
      if (kind === 'network') return route.abort('failed')
      if (kind === 'timeout') { await new Promise(resolve => setTimeout(resolve, 500)); return route.abort() }
      if (kind === 'http') return route.fulfill({ status: 503, contentType: 'text/html', body: '<h1>Unavailable</h1>' })
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body: kind === 'json'
        ? 'event: delta\ndata: invalid-json\n\n'
        : 'event: done\ndata: {"answer":123,"sources":[]}\n\n' })
    })
    await page.goto('/')
    await page.getByLabel('输入问题').fill('测试故障')
    await page.getByRole('button', { name: '发送问题' }).click()
    await expect(page.getByRole('alert')).toContainText({ network: '无法连接服务', http: 'HTTP 503', json: '数据格式无效', schema: '数据结构无效', timeout: '请求超时' }[kind])
    await expect(page.locator('.loading')).toHaveCount(0)
    await expect(page.getByTestId('message-assistant')).toHaveCount(0)
    await expect(page.getByLabel('输入问题')).toHaveValue('测试故障')
    await expect(page.getByRole('button', { name: '发送问题' })).toBeEnabled()
  })
}
