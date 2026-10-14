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

test('each agreement row names its judge', async ({ page }) => {
  await page.goto('/judge');
  const rows = page.getByTestId('agreement-row');
  const count = await rows.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(rows.nth(i).getByTestId('judge-slot')).not.toBeEmpty();
  }
});

test('two judges on one field type both render, each with its own judge', async ({ page }) => {
  // /judge/multi-judge-example is a static fixture route (see its folder): the committed
  // placeholder is left untouched.
  const response = await page.goto('/judge/multi-judge-example');
  expect(response?.ok()).toBe(true);
  const money = page.getByTestId('agreement-row').filter({ hasText: 'money' });
  await expect(money).toHaveCount(2);
  await expect(money.nth(0).getByTestId('judge-slot')).toHaveText('judge_a');
  await expect(money.nth(1).getByTestId('judge-slot')).toHaveText('judge_b');
});

test('inconclusive verdicts are tabulated as count of n per slot and judge', async ({ page }) => {
  await page.goto('/judge/multi-judge-example');
  const table = page.getByTestId('inconclusive-table');
  await expect(table).toBeVisible();
  const row = table.getByTestId('inconclusive-row').first();
  await expect(row).toContainText('slot_one');
  await expect(row).toContainText('judge_a');
  await expect(row).toContainText('3 of 12');
  await expect(page.getByTestId('inconclusive-note')).toContainText(/scored as incorrect/i);
});

test('a judge with no accepted decision is stated as not scored in the headline', async ({ page }) => {
  await page.goto('/judge/multi-judge-example');
  const rejected = page.getByTestId('agreement-row').filter({ hasText: 'judge_b' });
  await expect(rejected).toContainText(/rejected/i);
  await expect(page.getByTestId('threshold-notice')).toContainText(/not scored in the headline/i);
});

test('a payload with no inconclusive list says none are published', async ({ page }) => {
  await page.goto('/judge/degraded-example');
  await expect(page.getByTestId('inconclusive-empty')).toBeVisible();
});
