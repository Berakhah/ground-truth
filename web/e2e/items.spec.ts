import { expect, test } from '@playwright/test';

test('the explorer states that it shows the public split only', async ({ page }) => {
  await page.goto('/items');
  await expect(page.getByTestId('split-notice')).toContainText(/public split/i);
  await expect(page.getByTestId('split-notice')).toContainText(/withheld/i);
});

test('items can be filtered by failure mode', async ({ page }) => {
  await page.goto('/items');
  const before = await page.getByTestId('item-row').count();
  await page.getByLabel(/failure mode/i).selectOption({ index: 1 });
  await expect.poll(() => page.getByTestId('item-row').count()).toBeLessThan(before);
});

test('an empty filter result renders a denominator, not a celebration', async ({ page }) => {
  // Contract section 6.3: <EmptyState scope={{ measured, skipped, reason }} />
  await page.goto('/items');
  await page.getByLabel(/search/i).fill('zzzz-no-such-item');
  const empty = page.getByTestId('empty-state');
  await expect(empty).toContainText(/no items match/i);
  await expect(empty).toContainText(/of 120/, {
    // "0 of 120 public items match" -- never a bare "no results", which reads as
    // "nothing is wrong" when it actually means "nothing was measured".
  });
});
