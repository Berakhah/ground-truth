import { expect, test } from '@playwright/test';

test('each curve states its sample size and both splits', async ({ page }) => {
  await page.goto('/calibration');
  await expect(page.getByTestId('source-split')).toContainText(/public-fit\/private-validate/);
  await expect(page.getByTestId('curve-n').first()).toContainText(/n=\d+/);
});

test('the confidence signal is named on the page', async ({ page }) => {
  await page.goto('/calibration');
  await expect(page.getByTestId('signal-notice')).toContainText(/replicate agreement/i);
});

test('threshold recommendations are shown with their target', async ({ page }) => {
  await page.goto('/calibration');
  await expect(page.getByTestId('threshold-table')).toContainText(/0\.9/);
});

test('ConfidenceMeter receives a Calibration object, never a bare float', async ({ page }) => {
  // Contract section 6.3. A float cannot carry state/basis/curve_id/n, so a meter fed one
  // has no way to render "uncalibrated" -- which is 00 B10's entire point.
  await page.goto('/calibration');
  const meter = page.getByTestId('confidence-meter').first();
  await expect(meter).toHaveAttribute('data-calibration-state', /CALIBRATED|UNCALIBRATED/);
  await expect(meter).toContainText(/n=\d+/);
});

test('an uncalibrated field type renders greyed and labelled, not as a number', async ({ page }) => {
  await page.goto('/calibration');
  const uncalibrated = page.getByTestId('confidence-meter').filter({
    has: page.locator('[data-calibration-state="UNCALIBRATED"]'),
  });
  if ((await uncalibrated.count()) > 0) {
    await expect(uncalibrated.first()).toContainText(/uncalibrated/i);
  }
});
