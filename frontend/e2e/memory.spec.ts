import { test, expect } from '@playwright/test'

test('512MB 容器的真实公开 Demo：SSE 回答与来源', async ({ page }) => {
  test.skip(process.env.E2E_MEMORY !== '1', '仅对资源验证的真实容器执行')
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByText('服务已连接', { exact: true })).toBeVisible()
  await expect(page.getByLabel('上传 PDF')).toHaveCount(0)
  await page.getByLabel('输入问题').fill('Project Cedar 每位员工每月健康补贴是多少元？')
  const stream = page.waitForResponse(response => response.url().endsWith('/chat/stream'))
  await page.getByRole('button', { name: '发送问题' }).click()
  const response = await stream
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  await expect(page.getByTestId('message-assistant').last()).toContainText('731', { timeout: 120_000 })
  await expect(page.locator('.source-chip')).toContainText(['web-demo-policy.pdf第 1 页'], { timeout: 120_000 })
  await expect(page.locator('.loading')).toHaveCount(0)
  await page.getByLabel('输入问题').fill('下一轮问题')
  await expect(page.getByRole('button', { name: '发送问题' })).toBeEnabled()
  expect(errors).toEqual([])
})
