import { expect, test } from '@playwright/test';

test('every alert states the tests used', async ({ page }) => {
  await page.goto('/regression');
  const alerts = page.getByTestId('alert');
  const count = await alerts.count();
  for (let i = 0; i < count; i++) {
    await expect(alerts.nth(i)).toContainText(/O'Brien-Fleming/);
    await expect(alerts.nth(i)).toContainText(/Benjamini-Hochberg/);
  }
});

test('no alert is rendered as a bare arrow or bare percentage', async ({ page }) => {
  await page.goto('/regression');
  const alerts = page.getByTestId('alert');
  const count = await alerts.count();
  for (let i = 0; i < count; i++) {
    const text = (await alerts.nth(i).textContent()) ?? '';
    expect(text.replace(/[\s↑↓▲▼]/g, '').length).toBeGreaterThan(60);
  }
});

test('a null result states what was not detectable', async ({ page }) => {
  await page.goto('/regression');
  await expect(page.getByTestId('mde-notice')).toContainText(/not that none exists/i);
});

test('fingerprint status is published including where it is absent', async ({ page }) => {
  await page.goto('/regression');
  await expect(page.getByTestId('fingerprints')).toContainText(
    /does not expose|reported a single fingerprint/,
  );
});
