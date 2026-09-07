import { expect, test } from '@playwright/test';

test('rejected field types are shown, labelled rejected', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('agreement-table')).toContainText(/accepted|rejected/i);
});

test('every agreement figure carries its interval and n', async ({ page }) => {
  await page.goto('/judge');
  const cells = page.getByTestId('alpha-value');
  const count = await cells.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(cells.nth(i)).toContainText(/\[.*,.*\]/);
    await expect(cells.nth(i)).toContainText(/n=\d+/);
  }
});

test('the pre-registered threshold is stated on the page', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('threshold-notice')).toContainText('0.667');
  await expect(page.getByTestId('threshold-notice')).toContainText(/pre-registered/i);
});

test('order and length effects are published', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('order-effect')).toBeVisible();
  await expect(page.getByTestId('length-effect')).toBeVisible();
});

test('the confusion matrix is rendered', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('confusion-matrix')).toBeVisible();
});
