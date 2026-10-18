import { expect, test } from '@playwright/test';

// The simulated routes are developer-only fixtures (404 without GT_E2E_FIXTURES=1, which the
// Playwright web server sets). The run itself lives in data/simulated/, which CI does not have,
// so each route must read correctly both with a run and without one.
for (const route of ['/simulated-example', '/judge/simulated-example']) {
  test(`${route} says SIMULATED before anything else`, async ({ page }) => {
    await page.goto(route);
    await expect(page.getByTestId('simulated-banner')).toContainText('SIMULATED');
  });
}

test('the simulated leaderboard shows rows with intervals, or says there is no run', async ({ page }) => {
  await page.goto('/simulated-example');
  const rows = page.getByTestId('leaderboard-row');
  if ((await rows.count()) > 0) {
    await expect(rows.first()).toContainText(/sim-/);
    await expect(page.getByTestId('distinguishability')).toBeVisible();
  } else {
    await expect(page.getByTestId('simulated-banner')).toContainText('No usable simulated run');
  }
});
