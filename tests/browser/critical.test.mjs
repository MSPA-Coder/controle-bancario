import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.BASE_URL ?? 'http://browser-web:8000';

async function entrar(page) {
  await page.goto(`${base}/login`);
  await page.getByLabel('Usuário', { exact: true }).fill('browser');
  await page.getByLabel('Senha', { exact: true }).fill('Synthetic-browser-only-2026!');
  await Promise.all([page.waitForURL(url => !url.pathname.includes('login')), page.getByRole('button', { name: 'Entrar', exact: true }).click()]);
}

test('gravação HTMX atualiza saldo, renova a chave e preserva filtros', { timeout: 60000 }, async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  try {
    await entrar(page);
    await page.goto(`${base}/transactions/?currency=ALL&grupos=bancos&mode=realizado`);
    await page.getByRole('button', { name: 'Incluir', exact: true }).click();
    const form = page.locator('#newTransactionCard form');
    const initialToken = await form.locator('[name="submit_token"]').inputValue();
    await form.getByLabel('Conta', { exact: true }).selectOption({ label: 'Titular browser / Banco browser / Conta browser' });
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

// Titular > Instituição > Conta (tests/test_filtros_em_cascata.py tem o lado
// do servidor). Aqui, o que só o navegador faz: trocar um filtro de cima limpa
// a conta antes de a requisição sair.
test('trocar titular ou instituição reabre a lista de contas', { timeout: 60000 }, async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  const filtros = page.locator('#contextForm');
  // Espera a troca de #appMain terminar, não a URL: o endereço muda antes de
  // o cabeçalho ser trocado, e um filtro escolhido nesse intervalo cai no
  // formulário antigo, com a requisição anterior ainda em andamento.
  const escolher = async (rotulo, opcao) => {
    const trocou = page.evaluate(() => new Promise(resolve => {
      document.addEventListener('htmx:afterSettle', function fim(ev) {
        if (ev.target.id !== 'appMain') return;
        document.removeEventListener('htmx:afterSettle', fim);
        resolve();
      });
    }));
    await filtros.getByLabel(rotulo, { exact: true }).selectOption(opcao);
    await trocou;
  };
  const parametro = nome => new URL(page.url()).searchParams.get(nome);
  const contas = async () => (await filtros.getByLabel('Conta', { exact: true }).locator('option').allTextContents()).map(texto => texto.trim());
  try {
    await entrar(page);
    await page.goto(`${base}/transactions/?currency=ALL&grupos=bancos`);

    await escolher('Titular', { label: 'Titular browser' });
    await escolher('Conta', { label: 'Titular browser / Banco browser / Conta browser' });
    assert.ok(parametro('owner_id') && parametro('account_id'));
    // O relato: com a conta escolhida, as outras contas do titular sumiam.
    assert.deepEqual(await contas(), ['Todas as contas', 'Titular browser / Banco browser / Conta browser', 'Titular browser / Banco dois / Conta dois']);
    assert.ok((await filtros.getByLabel('Instituição', { exact: true }).locator('option').allTextContents()).includes('Banco dois'));

    await escolher('Titular', { label: 'Todos os titulares' });
    assert.equal(parametro('owner_id'), null);
    assert.equal(parametro('account_id'), null);
    assert.equal(await filtros.getByLabel('Conta', { exact: true }).inputValue(), '');
    assert.ok((await contas()).includes('Titular dois / Banco dois / Conta três'));

    // Conta compatível com a instituição escolhida também sai: escolher a
    // instituição é pedir para ver por ela.
    await escolher('Conta', { label: 'Titular dois / Banco dois / Conta três' });
    await escolher('Instituição', { label: 'Banco dois' });
    assert.ok(parametro('institution_id'));
    assert.equal(parametro('account_id'), null);
    assert.deepEqual(await contas(), ['Todas as contas', 'Titular browser / Banco dois / Conta dois', 'Titular dois / Banco dois / Conta três']);
  } catch (error) {
    await page.screenshot({ path: '/results/cb-filtros.png', fullPage: true });
    throw error;
  } finally { await browser.close(); }
});

// Duas guardas de front-end que só o navegador exercita: o diálogo de confirmação
// não abre antes da validação nativa, e o menu começa recolhido no celular.
test('novo lançamento inválido não abre a confirmação', { timeout: 60000 }, async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.setDefaultTimeout(15000);
  try {
    await entrar(page);
    await page.goto(`${base}/transactions/`);
    await page.getByRole('button', { name: 'Incluir', exact: true }).click();
    const form = page.locator('#newTransactionCard form');
    await form.getByRole('button', { name: 'Salvar', exact: true }).click();
    assert.equal(await page.getByRole('dialog').count(), 0);
    assert.equal(await form.evaluate(el => el.checkValidity()), false);
  } catch (error) {
    await page.screenshot({ path: '/results/cb-confirmacao.png', fullPage: true });
    throw error;
  } finally { await browser.close(); }
});

test('no celular o menu começa recolhido e o botão Menu o abre', { timeout: 60000 }, async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
  page.setDefaultTimeout(15000);
  try {
    await entrar(page);
    await page.goto(`${base}/transactions/`);
    const menu = page.locator('#appSidebar .sidebar-menu');
    assert.equal(await menu.isVisible(), false);
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    assert.equal(await menu.isVisible(), true);
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    assert.equal(await menu.isVisible(), false);
  } catch (error) {
    await page.screenshot({ path: '/results/cb-menu-celular.png', fullPage: true });
    throw error;
  } finally { await browser.close(); }
});
