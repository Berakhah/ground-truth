import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const ROUTES = ['/', '/items', '/judge', '/calibration', '/regression', '/triage'];

for (const route of ROUTES) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const blocking = results.violations.filter((v) =>
      ['serious', 'critical'].includes(v.impact ?? ''),
    );
    expect(blocking, JSON.stringify(blocking, null, 2)).toHaveLength(0);
  });

  test(`${route} keeps a visible focus ring throughout a tab sweep`, async ({ page }) => {
    await page.goto(route);
    const reached = new Set<string>();
    for (let i = 0; i < 60; i++) {
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const style = getComputedStyle(el);
        return {
          outline: style.outlineStyle,
          shadow: style.boxShadow,
          id: el.id || el.textContent?.slice(0, 20) || el.tagName,
        };
      });
      if (!focused) continue;
      expect(
        focused.outline !== 'none' || focused.shadow !== 'none',
        `${route}: focused element has no visible focus indicator`,
      ).toBe(true);
      reached.add(String(focused.id));
    }
    expect(reached.size).toBeGreaterThan(1);
  });

  test(`${route} does not scroll horizontally at 375px`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(route);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflow).toBe(false);
  });
}

test('status is never encoded in colour alone', async ({ page }) => {
  await page.goto('/regression');
  const badges = page.getByTestId('status-badge');
  const count = await badges.count();
  for (let i = 0; i < count; i++) {
    await expect(badges.nth(i)).not.toHaveText('');
  }
});
