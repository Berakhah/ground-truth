import { expect, test } from '@playwright/test';

// Locks in the post-review fix (task-46-report.md): artifacts/judge_agreement.json's
// placeholder was originally modeled on the wrong emitter (leaderboard.py's
// _agreement_to_dict -- nested alpha_ci, uppercase status, a statement field), when the
// function that actually writes this exact file, artifacts.py's emit_all, produces a flatter,
// narrower shape with no order_effect/length_effect/confusion_matrix and no per-decision
// statement. /judge/degraded-example is a second static route rendering the same
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

  // Still renders every element the plan requires, just with an honest not-measured state.
  await expect(page.getByTestId('order-effect')).toContainText(/not yet measured/i);
  await expect(page.getByTestId('length-effect')).toContainText(/not yet measured/i);
  await expect(page.getByTestId('confusion-matrix')).toContainText(/not yet measured/i);

  // The parts emit_all() DOES produce today still render correctly with no statement field.
  await expect(page.getByTestId('agreement-table')).toContainText(/accepted/i);
  await expect(page.getByTestId('agreement-table')).toContainText(/rejected/i);
  const alphaValues = page.getByTestId('alpha-value');
  await expect(alphaValues).toHaveCount(2);
  await expect(alphaValues.first()).toContainText(/\[.*,.*\]/);
  await expect(alphaValues.first()).toContainText(/n=\d+/);

  // Threshold notice still resolves from decisions[0].threshold, not left blank.
  await expect(page.getByTestId('threshold-notice')).toContainText('0.667');
});
