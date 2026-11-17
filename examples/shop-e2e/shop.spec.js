const { test, expect } = require('@playwright/test');
const path = require('path');
const url = require('url').pathToFileURL(path.resolve(__dirname, 'page.html')).href;
test('checkout shows confirmation', async ({ page }) => {
  await page.route('https://shop.test/api/charge', r => r.fulfill({ status: 500, body: 'boom', headers: {'access-control-allow-origin': '*'} }));
  await page.goto(url);
  await page.getByPlaceholder('you@example.com').fill('buyer-one');
  await page.getByRole('button', { name: 'Pay now' }).click();
  await expect(page.locator('#status')).toHaveText('Payment confirmed', { timeout: 2000 });
});
test('heading visible', async ({ page }) => {
  await page.goto(url);
  await expect(page.getByRole('heading', { name: 'Checkout' })).toBeVisible();
});
test('missing button click times out', async ({ page }) => {
  await page.goto(url);
  await page.getByRole('button', { name: 'Refund' }).click({ timeout: 1500 });
});
test('coupon call is aborted and page throws', async ({ page }) => {
  await page.route('https://shop.test/api/coupon', r => r.abort('connectionrefused'));
  await page.goto(url);
  await page.evaluate(() => {
    fetch('https://shop.test/api/coupon', { method: 'POST', body: JSON.stringify({ code: 'SAVE10' }) }).catch(() => {});
    setTimeout(() => { throw new Error('coupon widget exploded'); }, 0);
  });
  await expect(page.locator('#status')).toHaveText('Coupon applied', { timeout: 1500 });
});
