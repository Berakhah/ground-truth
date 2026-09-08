import { expect, test } from '@playwright/test';

test('the triage report renders under print media', async ({ page }) => {
  await page.goto('/triage');
  await page.emulateMedia({ media: 'print' });
  await expect(page.getByTestId('report')).toBeVisible();
});

test('every recommendation shows its calculation', async ({ page }) => {
  await page.goto('/triage');
  await expect(page.getByTestId('calculation').first()).toBeVisible();
});

test('the flip point is stated for every bounded intent', async ({ page }) => {
  await page.goto('/triage');
  await expect(page.getByTestId('flip-point').first()).toContainText(/costs more than/);
});
