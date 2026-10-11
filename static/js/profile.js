(function () {
    "use strict";

    initLocalePreview();

    var form = document.getElementById("theme-form");
    if (!form) return;

    var selected = form.querySelector('input[name="theme"]:checked');
    form.querySelectorAll('input[name="theme"]').forEach(function (input) {
        input.addEventListener("change", function () {
            var previous = selected;
            if (!window.sharedauth || typeof window.sharedauth.confirmar !== "function") {
                input.checked = false;
                if (previous) previous.checked = true;
                return;
            }
            window.sharedauth.confirmar({
                mensagem: "Salvar este tema como sua preferência?",
                titulo: "Confirmar tema",
                severidade: "info"
            }).then(function (ok) {
                if (!ok) {
                    input.checked = false;
                    if (previous) previous.checked = true;
                    return;
                }
                selected = input;
                form.requestSubmit();
            });
        });
    });

    /* Prévia de "Idioma e região": mostra como data, número, valor e hora ficam
       com a escolha ainda não salva. Os textos já vêm prontos do servidor
       (`data-preview*` nos radios); aqui só se escolhe qual mostrar. */
    function initLocalePreview() {
        var localeForm = document.getElementById("locale-form");
        var preview = document.getElementById("locale-preview");
        if (!localeForm || !preview) return;

        function refresh() {
            var language = localeForm.querySelector('input[name="language"]:checked');
            var region = localeForm.querySelector('input[name="regional_format"]:checked');
            if (!region) return;
            var text = region.getAttribute("data-preview") || "";
            // `auto` segue o idioma: a prévia dele muda com o idioma escolhido.
            var byLanguage = language && region.getAttribute("data-preview-" + language.value);
            preview.textContent = byLanguage || text;
        }

        localeForm.addEventListener("change", refresh);
        refresh();
    }
})();
