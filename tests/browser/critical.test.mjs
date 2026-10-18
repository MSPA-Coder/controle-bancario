import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

test('gravação HTMX atualiza saldo, renova a chave e preserva filtros', { timeout: 60000 }, async () => {
  const base = process.env.BASE_URL ?? 'http://browser-web:8000';
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  try {
    await page.goto(`${base}/login`);
    await page.getByLabel('Usuário', { exact: true }).fill('browser');
    await page.getByLabel('Senha', { exact: true }).fill('Synthetic-browser-only-2026!');
    await Promise.all([page.waitForURL(url => !url.pathname.includes('login')), page.getByRole('button', { name: 'Entrar', exact: true }).click()]);
    await page.goto(`${base}/transactions/?currency=ALL&grupos=bancos&mode=realizado`);
    await page.getByRole('button', { name: 'Incluir', exact: true }).click();
    const form = page.locator('#newTransactionCard form');
    const initialToken = await form.locator('[name="submit_token"]').inputValue();
    await form.getByLabel('Conta', { exact: true }).selectOption({ label: 'Banco browser / Conta browser' });
    await form.getByLabel('Categoria', { exact: true }).selectOption({ label: 'Despesa browser' });
    await form.getByLabel('Tipo', { exact: true }).selectOption('despesa');
    await form.getByLabel('Status', { exact: true }).selectOption('realizado');
    await form.getByLabel('Descrição', { exact: true }).fill('Browser HTMX');
    await form.getByRole('textbox', { name: 'Valor total', exact: true }).fill('12,34');
    const iso = await form.locator('[name="due_date"]').inputValue();
    const [year, month, day] = iso.split('-');
    await form.getByRole('textbox', { name: 'Data de realização', exact: true }).fill(`${day}/${month}/${year}`);
    await form.getByRole('textbox', { name: 'Valor realizado', exact: true }).fill('12,34');
    await form.getByLabel('Descrição', { exact: true }).focus();
    await form.getByRole('button', { name: 'Salvar', exact: true }).click();
    const response = page.waitForResponse(r => r.request().method() === 'POST' && new URL(r.url()).pathname === '/transaction/');
    await page.getByRole('dialog').getByRole('button', { name: 'Salvar', exact: true }).click();
    // O middleware transforma o 204 em 200 para entregar mensagens fora de banda.
    const saved = await response;
    assert.equal(saved.status(), 200);
    assert.equal(JSON.parse(saved.headers()['hx-trigger']).tableRefresh, true);
    await page.locator('#transactions-table-container').getByText('Browser HTMX', { exact: true }).waitFor();
    assert.match(await page.locator('#transactions-summary').innerText(), /987,66/);
    assert.notEqual(await form.locator('[name="submit_token"]').inputValue(), initialToken);
    assert.equal(new URL(page.url()).searchParams.get('currency'), 'ALL');
    assert.equal(new URL(page.url()).searchParams.get('grupos'), 'bancos');
    await page.reload();
    assert.match(await page.locator('#transactions-summary').innerText(), /987,66/);
    assert.equal(await page.locator('#transactions-table-container').getByText('Browser HTMX', { exact: true }).count(), 1);
  } catch (error) {
    await page.screenshot({ path: '/results/cb-htmx.png', fullPage: true });
    throw error;
  } finally { await browser.close(); }
});
