import { expect, test } from '@playwright/test';

test('every accuracy figure is rendered as an interval, not a bare number', async ({ page }) => {
  await page.goto('/');
  const rows = page.getByTestId('leaderboard-row');
  const count = await rows.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(rows.nth(i).getByTestId('accuracy-interval')).toBeVisible();
    await expect(rows.nth(i).getByTestId('accuracy-n')).toContainText(/n=\d+/);
  }
});

test('overlapping models are described in words', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('distinguishability')).toContainText(
    /not distinguishable at this sample size|All models are distinguishable/,
  );
});

test('a judged field type left out of the numbers is named, with its reason', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('held-back')).toContainText(
    /line_item_description \(judging incomplete/,
  );
});

test('the methodology link sits beside the title, not in the footer', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('banner').getByRole('link', { name: /methodology/i })).toBeVisible();
});

test('the cost column states that it is list price', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('cost-caveat')).toContainText(/list price/i);
});

test('latency is not sortable', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('columnheader', { name: /latency/i }).getByRole('button'),
  ).toHaveCount(0);
});

test('the page is operable by keyboard alone', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.locator(':focus')).toBeVisible();
});

test('a visible banner flags placeholder data as not a real measurement', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('placeholder-banner')).toBeVisible();
  await expect(page.getByTestId('placeholder-banner')).toContainText(
    /placeholder|no live measurement|demo/i,
  );
});

test('the latency free-tier caveat reaches assistive tech, not just hover/print', async ({ page }) => {
  await page.goto('/');
  // Reads textContent directly rather than asserting visibility: this element is
  // intentionally visually-hidden (same technique as the table's own caption) --
  // the point is that it's in the accessibility tree without requiring a hover.
  await expect(page.getByTestId('latency-caveat')).toHaveText(/free tier/i);
});
