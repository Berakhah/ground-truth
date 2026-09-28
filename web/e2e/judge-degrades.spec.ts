import { expect, test } from '@playwright/test';

// Locks in the post-review fix (task-46-report.md): artifacts/judge_agreement.json's
// placeholder was originally modeled on the wrong emitter (leaderboard.py's
// _agreement_to_dict -- nested alpha_ci, uppercase status, a statement field), when the
// function that actually writes this exact file, artifacts.py's emit_all, produces a flatter,
// narrower shape with no order_effect/length_effect/confusion_matrix (it does now carry each
// decision's stored statement). /judge/degraded-example is a second static route rendering the same
// JudgeAgreementView against a payload shaped like that real, narrower output -- proving the
// page degrades to an honest "not yet measured" state instead of crashing on `undefined`.

test('the rich placeholder still shows real order/length/confusion data', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('order-effect')).toContainText(/order effect on money/i);
  await expect(page.getByTestId('length-effect')).toContainText(/length effect on money/i);
  await expect(page.getByTestId('confusion-matrix')).toBeVisible();
  await expect(page.getByTestId('order-effect')).not.toContainText(/not yet measured/i);
});

test('a real, narrower emit_all-shaped payload degrades instead of crashing', async ({ page }) => {
  const response = await page.goto('/judge/degraded-example');
  expect(response?.ok()).toBe(true);

  // Ships in the static export like any other route, so it needs the same synthetic-data
  // disclosure every other page gives (review finding, post task-46) -- not just being
  // unlinked from the real nav.
  await expect(page.getByTestId('placeholder-banner')).toBeVisible();

  // Still renders every element the plan requires, just with an honest not-measured state.
  await expect(page.getByTestId('order-effect')).toContainText(/not yet measured/i);
  await expect(page.getByTestId('length-effect')).toContainText(/not yet measured/i);
  await expect(page.getByTestId('confusion-matrix')).toContainText(/not yet measured/i);

  // The parts emit_all() DOES produce today still render correctly with no statement field.
  await expect(page.getByTestId('agreement-table')).toContainText(/accepted/i);
  await expect(page.getByTestId('agreement-table')).toContainText(/rejected/i);
  const alphaValues = page.getByTestId('alpha-value');
  await expect(alphaValues).toHaveCount(4);
  await expect(alphaValues.first()).toContainText(/\[.*,.*\]/);
  await expect(alphaValues.first()).toContainText(/n=\d+/);

  // Threshold notice still resolves from decisions[0].threshold, not left blank.
  await expect(page.getByTestId('threshold-notice')).toContainText('0.667');
});

test('an undefined alpha (published as null) renders in words, with its reason', async ({ page }) => {
  // emit_all publishes a 0/0 alpha as JSON null plus a statement (stats code review
  // 2026-09-27, finding 5). IntervalBar used to call null.toFixed and take the build down.
  const response = await page.goto('/judge/degraded-example');
  expect(response?.ok()).toBe(true);
  const row = page.getByTestId('agreement-row').filter({ hasText: 'currency_code' });
  await expect(row.getByTestId('alpha-value')).toContainText(/undefined/i);
  await expect(row.getByTestId('alpha-value')).toContainText('n=60');
  await expect(row).toContainText(/same verdict/i);
  await expect(row).toContainText(/rejected/i);
});

test('a defined alpha whose interval could not be estimated says so, not "Undefined"', async ({ page }) => {
  // Every bootstrap resample was 0/0, so alpha_low/alpha_high publish as null while alpha itself
  // is defined (stats code review 2026-09-27 #2, finding 5). Calling alpha "Undefined" there
  // would misstate a number that was measured.
  const response = await page.goto('/judge/degraded-example');
  expect(response?.ok()).toBe(true);
  const row = page.getByTestId('agreement-row').filter({ hasText: 'invoice_number' });
  await expect(row.getByTestId('alpha-value')).toContainText('0.000');
  await expect(row.getByTestId('alpha-value')).toContainText(/interval not estimable/i);
  await expect(row.getByTestId('alpha-value')).toContainText('n=10');
  await expect(row.getByTestId('alpha-value')).not.toContainText(/undefined/i);
});
