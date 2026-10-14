/* Rolagem horizontal arrastando ("mãozinha").
 *
 * Em qualquer área que role na horizontal, segurar o botão ESQUERDO do mouse e
 * arrastar para os lados rola o conteúdo. Vale para tabelas e painéis de todas
 * as telas sem marcação própria: a área é descoberta no momento do clique
 * (primeiro ancestral com `overflow-x` auto/scroll e conteúdo mais largo que a
 * caixa), então conteúdo trocado por HTMX também funciona. Sobre uma área que
 * rola, o cursor vira a mãozinha (`grab`).
 *
 * Como o botão esquerdo também clica e seleciona texto, o arrasto é prudente:
 * - não começa sobre link, botão, campo de formulário, rótulo, imagem ou
 *   `[data-no-drag-scroll]`, nem sobre a barra de rolagem, nem com Shift, Ctrl,
 *   Alt ou Meta, nem em duplo/triplo clique (que seleciona palavra e linha);
 * - só vira arrasto depois de LIMIAR pixels, e só se o gesto for mais
 *   horizontal que vertical: arrastar para baixo continua selecionando linhas;
 * - ao virar arrasto, a seleção de texto é descartada e a página para de
 *   selecionar até soltar o botão;
 * - o clique que o navegador geraria ao soltar (sobre um link, uma linha) é
 *   descartado, para arrastar não abrir nada;
 * - o arrasto termina sozinho se a área sair do DOM (troca HTMX), a janela
 *   perder o foco ou o botão for solto fora da janela.
 */
(function () {
    'use strict';

    if (window.__dragScrollIniciado) return;
    window.__dragScrollIniciado = true;

    var LIMIAR = 6;
    var CLASSE_AREA = 'is-drag-scrolling';
    var CLASSE_RAIZ = 'drag-scrolling';
    var CLASSE_PRONTA = 'drag-scroll-ready';
    var IGNORADOS = 'a, button, input, select, textarea, label, summary, img, [role="button"], ' +
        '[contenteditable]:not([contenteditable="false"]), [draggable="true"], [data-no-drag-scroll]';

    var estado = null;
    var suprimirClique = false;
    var temporizadorDoClique = null;
    var areaPronta = null;

    function rolaNaHorizontal(el) {
        if (el.scrollWidth <= el.clientWidth + 1) return false;
        var overflowX = window.getComputedStyle(el).overflowX;
        return overflowX === 'auto' || overflowX === 'scroll' || overflowX === 'overlay';
    }

    function areaDeRolagem(alvo) {
        var el = alvo instanceof Element ? alvo : null;
        while (el && el !== document.documentElement) {
            if (rolaNaHorizontal(el)) return el;
            el = el.parentElement;
        }
        return null;
    }

    function naBarraDeRolagem(area, evento) {
        var caixa = area.getBoundingClientRect();
        return evento.clientX - caixa.left >= area.clientWidth || evento.clientY - caixa.top >= area.clientHeight;
    }

    function encerrar() {
        if (!estado) return;
        estado.area.classList.remove(CLASSE_AREA);
        document.documentElement.classList.remove(CLASSE_RAIZ);
        estado = null;
    }

    // A mãozinha só aparece onde há o que arrastar.
    document.addEventListener('mouseover', function (evento) {
        if (estado) return;
        var area = areaDeRolagem(evento.target);
        if (area === areaPronta) return;
        if (areaPronta) areaPronta.classList.remove(CLASSE_PRONTA);
        areaPronta = area;
        if (areaPronta) areaPronta.classList.add(CLASSE_PRONTA);
    }, true);

    document.addEventListener('mousedown', function (evento) {
        if (evento.button !== 0) return;
        // Um novo clique zera qualquer gesto anterior que tenha ficado preso.
        encerrar();
        suprimirClique = false;
        if (evento.detail > 1 || evento.shiftKey || evento.ctrlKey || evento.altKey || evento.metaKey) return;
        if (!(evento.target instanceof Element) || evento.target.closest(IGNORADOS)) return;
        var area = areaDeRolagem(evento.target);
        if (!area || naBarraDeRolagem(area, evento)) return;
        estado = {
            area: area,
            inicioX: evento.clientX,
            inicioY: evento.clientY,
            inicioRolagem: area.scrollLeft,
            arrastando: false
        };
    }, true);

    document.addEventListener('mousemove', function (evento) {
        if (!estado) return;
        // Botão esquerdo solto fora da janela: não houve mouseup aqui.
        if (!(evento.buttons & 1) || !estado.area.isConnected) {
            encerrar();
            return;
        }
        var deslocamentoX = evento.clientX - estado.inicioX;
        if (!estado.arrastando) {
            var deslocamentoY = evento.clientY - estado.inicioY;
            // Gesto mais vertical que horizontal: é seleção de linhas, não arrasto.
            if (Math.abs(deslocamentoY) >= LIMIAR && Math.abs(deslocamentoY) > Math.abs(deslocamentoX)) {
                estado = null;
                return;
            }
            if (Math.abs(deslocamentoX) < LIMIAR) return;
            estado.arrastando = true;
            estado.area.classList.add(CLASSE_AREA);
            document.documentElement.classList.add(CLASSE_RAIZ);
            var selecao = window.getSelection && window.getSelection();
            if (selecao) selecao.removeAllRanges();
        }
        estado.area.scrollLeft = estado.inicioRolagem - deslocamentoX;
    }, true);

    document.addEventListener('mouseup', function (evento) {
        if (evento.button !== 0 || !estado) return;
        var arrastou = estado.arrastando;
        encerrar();
        if (!arrastou) return;
        // O clique chega logo depois do mouseup e abriria o que estiver sob o cursor.
        suprimirClique = true;
        window.clearTimeout(temporizadorDoClique);
        temporizadorDoClique = window.setTimeout(function () { suprimirClique = false; }, 100);
    }, true);

    document.addEventListener('click', function (evento) {
        if (!suprimirClique) return;
        suprimirClique = false;
        evento.preventDefault();
        evento.stopPropagation();
    }, true);

    window.addEventListener('blur', encerrar);
    document.addEventListener('dragstart', encerrar, true);
}());
