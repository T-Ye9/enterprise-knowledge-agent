import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e', workers: 1, timeout: 180_000,
  use: { baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173',
    browserName: 'chromium', channel: 'msedge', viewport: { width: 1440, height: 1000 },
    screenshot: 'only-on-failure' },
  reporter: [['list'], ['json', { outputFile: 'test-results/results.json' }]],
})
