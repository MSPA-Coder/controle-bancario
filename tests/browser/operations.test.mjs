import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.BASE_URL ?? 'http://browser-web:8000';

async function entrar(page) {
  await page.goto(`${base}/login`);
  await page.getByLabel('Usuário', { exact: true }).fill('browser');
  await page.getByLabel('Senha', { exact: true }).fill('Synthetic-browser-only-2026!');
  await Promise.all([
    page.waitForURL(url => !url.pathname.includes('login')),
    page.getByRole('button', { name: 'Entrar', exact: true }).click(),
  ]);
}

test('Ver operação abre só as parcelas selecionadas e permite recolher', { timeout: 60000 }, async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  try {
    await entrar(page);
    await page.goto(`${base}/operations/`);
    const rows = page.locator('tr.details-row');
    assert.equal(await rows.count(), 2);
    assert.equal(await page.locator('.details-row:visible').count(), 0);

    const link = page.locator('a[title="Ver operação"][href*="operation_id=browser-operation-expansion&"]');
    const requestPromise = page.waitForRequest(request => new URL(request.url()).pathname === '/operations/');
    await link.click();
    const request = await requestPromise;
    assert.equal(request.headers()['hx-request'], undefined);
    assert.match(page.url(), /operation_id=browser-operation-expansion/);

    const details = page.locator('.details-row[data-ui="table-row"]');
    await details.waitFor({ state: 'visible' });
    assert.equal(await details.locator('.nested-table tbody tr').count(), 3);
    assert.match(await details.innerText(), /Compra de teste parcelada parcela 1/);
    assert.match(await details.innerText(), /Compra de teste parcelada parcela 3/);
    assert.doesNotMatch(await details.innerText(), /Outra compra de teste/);
    assert.equal(await page.locator('.details-row[data-ui="table-row"]').count(), 1);

    const htmxResponse = await page.evaluate(async path => {
      const response = await fetch(path, { headers: { 'HX-Request': 'true' } });
      return { status: response.status, body: await response.text() };
    }, `${base}/operations/?operation_id=browser-operation-expansion&show_entries=1`);
    assert.equal(htmxResponse.status, 200);
    assert.match(htmxResponse.body, /id="operations-results"/);
    assert.match(htmxResponse.body, /Compra de teste parcelada parcela 2/);
    assert.doesNotMatch(htmxResponse.body, /<!doctype html/i);

    await page.getByRole('link', { name: 'Ocultar detalhes' }).click();
    await page.waitForFunction(() => document.querySelectorAll('.details-row[data-ui="table-row"]').length === 0);
    assert.equal(await page.locator('.details-row:visible').count(), 0);
    // Recolher fica na operação escolhida, em vez de abrir a lista global.
    assert.match(page.url(), /operation_id=browser-operation-expansion/);
    assert.equal(await page.locator('tr.details-row').count(), 1);
    await page.goto(`${base}/operations/`);
    assert.equal(await page.locator('tr.details-row').count(), 2);
    assert.equal(await page.locator('.details-row:visible').count(), 0);
  } finally {
    await browser.close();
  }
});
