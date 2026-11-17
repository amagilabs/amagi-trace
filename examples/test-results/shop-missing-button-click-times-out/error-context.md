# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: shop.spec.js >> missing button click times out
- Location: shop.spec.js:15:1

# Error details

```
TimeoutError: locator.click: Timeout 1500ms exceeded.
Call log:
  - waiting for getByRole('button', { name: 'Refund' })

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - heading "Checkout" [level=1] [ref=e2]
  - generic [ref=e3]:
    - generic [ref=e4]:
      - text: Email
      - textbox "Email" [ref=e5]:
        - /placeholder: you@example.com
    - button "Pay now" [ref=e6]
  - paragraph [ref=e7]: Ready
```

# Test source

```ts
  1  | const { test, expect } = require('@playwright/test');
  2  | const path = require('path');
  3  | const url = require('url').pathToFileURL(path.resolve(__dirname, 'page.html')).href;
  4  | test('checkout shows confirmation', async ({ page }) => {
  5  |   await page.route('https://shop.test/api/charge', r => r.fulfill({ status: 500, body: 'boom', headers: {'access-control-allow-origin': '*'} }));
  6  |   await page.goto(url);
  7  |   await page.getByPlaceholder('you@example.com').fill('buyer-one');
  8  |   await page.getByRole('button', { name: 'Pay now' }).click();
  9  |   await expect(page.locator('#status')).toHaveText('Payment confirmed', { timeout: 2000 });
  10 | });
  11 | test('heading visible', async ({ page }) => {
  12 |   await page.goto(url);
  13 |   await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible();
  14 | });
  15 | test('missing button click times out', async ({ page }) => {
  16 |   await page.goto(url);
> 17 |   await page.getByRole('button', { name: 'Refund' }).click({ timeout: 1500 });
     |                                                      ^ TimeoutError: locator.click: Timeout 1500ms exceeded.
  18 | });
  19 | test('coupon call is aborted and page throws', async ({ page }) => {
  20 |   await page.route('https://shop.test/api/coupon', r => r.abort('connectionrefused'));
  21 |   await page.goto(url);
  22 |   await page.evaluate(() => {
  23 |     fetch('https://shop.test/api/coupon', { method: 'POST', body: JSON.stringify({ code: 'SAVE10' }) }).catch(() => {});
  24 |     setTimeout(() => { throw new Error('coupon widget exploded'); }, 0);
  25 |   });
  26 |   await expect(page.locator('#status')).toHaveText('Coupon applied', { timeout: 1500 });
  27 | });
  28 | 
```