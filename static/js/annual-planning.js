/* Pequenos aprimoramentos de acessibilidade para a tabela longa. */
(function () {
    function initAnnualPlanning(root) {
        (root || document).querySelectorAll('[data-annual-planning-table]').forEach(function (tableWrap) {
            if (tableWrap.dataset.annualPlanningBound === '1') return;
            tableWrap.dataset.annualPlanningBound = '1';

            var table = tableWrap.querySelector('table');
            if (table) {
                tableWrap.addEventListener('keydown', function (event) {
                    if (event.key !== 'Home' && event.key !== 'End') return;
                    if (event.target.closest('input, select, textarea, button, a')) return;
                    tableWrap.scrollLeft = event.key === 'Home' ? 0 : tableWrap.scrollWidth;
                });
            }
        });

        // Cada moeda tem o seu par resumo + grade, um logo após o outro; o par
        // rola junto, e um par não mexe no outro.
        document.querySelectorAll('.annual-summary-wrap').forEach(function (summaryWrap) {
            var planningWrap = summaryWrap.nextElementSibling;
            if (!planningWrap || !planningWrap.matches('[data-annual-planning-table]')) return;
            if (summaryWrap.dataset.annualPlanningScrollBound === '1') return;
            summaryWrap.dataset.annualPlanningScrollBound = '1';
            planningWrap.dataset.annualPlanningScrollBound = '1';
            mirrorScroll(summaryWrap, planningWrap);
        });
    }

    /* O evento `scroll` é assíncrono: uma trava booleana ao redor da escrita não
       impede o eco, e com larguras diferentes o lado arrastado era puxado de
       volta. Cada lado lembra o valor que o OUTRO acabou de gravar nele (já
       limitado pela largura dele) e ignora o evento que esse valor provoca. */
    function mirrorScroll(first, second) {
        var echo = new Map([[first, null], [second, null]]);
        function follow(source, target) {
            source.addEventListener('scroll', function () {
                if (echo.get(source) === source.scrollLeft) {
                    echo.set(source, null);
                    return;
                }
                echo.set(source, null);
                var before = target.scrollLeft;
                target.scrollLeft = source.scrollLeft;
                echo.set(target, target.scrollLeft === before ? null : target.scrollLeft);
            });
        }
        follow(first, second);
        follow(second, first);
    }

    document.addEventListener('DOMContentLoaded', function () { initAnnualPlanning(document); });
    document.addEventListener('app:contentLoaded', function (event) { initAnnualPlanning(event.target); });
    document.addEventListener('htmx:afterSwap', function (event) { initAnnualPlanning(event.target); });
}());
