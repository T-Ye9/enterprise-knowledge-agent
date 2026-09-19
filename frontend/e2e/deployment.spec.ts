import { test, expect } from '@playwright/test'

test('公开 Demo 隐藏上传入口，聊天仍可使用', async ({ page }) => {
  test.skip(process.env.E2E_READONLY !== '1', '需要 VITE_ALLOW_DOCUMENT_UPLOAD=false 的前端服务')
  await page.route('**/health', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{"status":"ok"}' }))
  await page.route('**/chat/stream', route => route.fulfill({ status: 200, contentType: 'text/event-stream', body:
    'event: done\ndata: {"answer":"你好！","session_id":"00000000-0000-0000-0000-000000000001","sources":[]}\n\n' }))
  await page.goto('/')
  await expect(page.getByLabel('上传 PDF')).toHaveCount(0)
  await expect(page.getByText('基于公开示例文档，直接提问。', { exact: false })).toBeVisible()
  await page.getByLabel('输入问题').fill('你好')
  await page.getByRole('button', { name: '发送问题' }).click()
  await expect(page.getByTestId('message-assistant')).toContainText('你好！')
  await expect(page.locator('.loading')).toHaveCount(0)
})
