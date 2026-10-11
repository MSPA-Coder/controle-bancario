# Extrai os textos marcados para traducao (`_()`, `{% trans %}`...) e atualiza
# `locale/en/LC_MESSAGES/django.po`. O texto em portugues e o msgid; a traducao
# inglesa fica em `msgstr`.
#
# Roda no conteiner de qualidade (que tem o GNU gettext). O sistema de arquivos
# dele e somente leitura e o `makemessages` escreve arquivos temporarios ao lado
# dos templates, entao a extracao acontece numa copia em /tmp e so o `.po` volta
# para a pasta `locale/`, a unica montada para escrita. `--build` faz parte do
# comando: sem ele a extracao leria a versao anterior do codigo.
#
#   .\scripts\mensagens.ps1            # atualiza o .po
#   .\scripts\mensagens.ps1 -Conferir  # so confere se o .po esta atualizado (CI/pre-PR)
#
# No Windows PowerShell 5.1 o `docker` escreve progresso em stderr e o PowerShell
# o trata como erro; por isso o codigo de saida e o que vale, nao a mensagem.
param([switch]$Conferir)

$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$ignorar = "-i 'tests/*' -i 'static/*' -i 'staticfiles/*' -i 'docs/*' -i 'scripts/*' -i '.venv/*' -i '*/migrations/*' -i '*/management/commands/*'"
$po = "locale/en/LC_MESSAGES/django.po"
$extrair = "cp -r /workspace /tmp/w && cd /tmp/w && django-admin makemessages -l en --no-obsolete --no-wrap --add-location=file $ignorar >/dev/null"

if ($Conferir) {
    # A data de criacao do cabecalho muda a cada extracao e nao conta.
    $comando = "$extrair && diff -I '^`"POT-Creation-Date' /tmp/w/$po /workspace/$po"
} else {
    $comando = "$extrair && cp /tmp/w/$po /workspace/$po"
}

$montagem = "${raiz}/locale:/workspace/locale"
$ErrorActionPreference = 'Continue'
docker compose --env-file .env.docker -f compose.yaml --profile quality run --build --rm `
    -v $montagem quality sh -c $comando 2>&1 | Out-Host
exit $LASTEXITCODE
