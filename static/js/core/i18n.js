/* Textos do JavaScript no idioma do usuário.

   `t('Texto em português')` devolve o texto no idioma ativo; sem tradução (ou sem
   o JSON), devolve o próprio texto. Os textos vêm prontos do servidor no JSON
   `#i18n-js` (`core/textos_js.py`): não há catálogo no navegador. `%(nome)s`
   recebe valores do segundo argumento: `t('Faltam %(n)s', {n: 3})`.

   Também dá idioma aos diálogos de confirmação do SharedAuth. Eles trariam
   "Cancelar" e "Confirmar" em português sempre que o elemento não passa
   `data-sa-cancelar`, `data-sa-ok` e `data-sa-titulo`; aqui o que faltar é
   preenchido. O SharedAuth lê esses atributos no clique, então basta estarem lá. */
(function () {
    'use strict';

    var DICT = {};
    try {
        var el = document.getElementById('i18n-js');
        if (el) DICT = JSON.parse(el.textContent) || {};
    } catch (e) {
        DICT = {};
    }

    function t(text, vars) {
        var out = Object.prototype.hasOwnProperty.call(DICT, text) ? DICT[text] : text;
        if (vars) {
            out = out.replace(/%\((\w+)\)s/g, function (whole, name) {
                return Object.prototype.hasOwnProperty.call(vars, name) ? vars[name] : whole;
            });
        }
        return out;
    }

    window.t = t;

    function fillConfirmDefaults(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var found = Array.prototype.slice.call(scope.querySelectorAll('[data-sa-confirmar]'));
        if (scope.matches && scope.matches('[data-sa-confirmar]')) found.push(scope);
        found.forEach(function (node) {
            if (!node.hasAttribute('data-sa-cancelar')) node.setAttribute('data-sa-cancelar', t('Cancelar'));
            if (!node.hasAttribute('data-sa-ok')) node.setAttribute('data-sa-ok', t('Confirmar'));
            if (!node.hasAttribute('data-sa-titulo')) node.setAttribute('data-sa-titulo', t('Confirmar'));
        });
    }

    function start() {
        fillConfirmDefaults(document);
        // Trechos trocados pelo HTMX também podem trazer diálogos.
        new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1) fillConfirmDefaults(node);
                });
            });
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
}());
