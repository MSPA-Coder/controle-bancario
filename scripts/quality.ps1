# Executa o portão de qualidade sem permitir que duas execuções do mesmo
# checkout disputem o PostgreSQL efêmero `postgres-teste`. Uma segunda chamada
# aguarda a primeira terminar antes de o Compose poder recriar qualquer serviço.
#
#   .\scripts\quality.ps1
#   .\scripts\quality.ps1 run --build --rm quality mypy

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ComposeArguments = @($args)
if ($ComposeArguments.Count -eq 0) {
    $ComposeArguments = @('run', '--build', '--rm', 'quality')
}

$root = Split-Path -Parent $PSScriptRoot
# O mutex pertence ao host, não ao contêiner: ele cobre também o intervalo em
# que o Compose prepara ou recria `postgres-teste`, antes de o runner existir.
$mutex = New-Object System.Threading.Mutex($false, 'Global\ControleBancario.Quality')
$acquired = $false
$exitCode = 1

try {
    Write-Host 'Aguardando exclusão mútua da suíte quality, se necessário...'
    try {
        $acquired = $mutex.WaitOne([TimeSpan]::FromMinutes(45))
    } catch [System.Threading.AbandonedMutexException] {
        # A execução anterior caiu; o Windows já concedeu o mutex a esta.
        $acquired = $true
        Write-Warning 'A execução quality anterior terminou inesperadamente; retomando a trava.'
    }

    if (-not $acquired) {
        throw 'A suíte quality ficou ocupada por mais de 45 minutos. Verifique a execução anterior antes de tentar novamente.'
    }

    Push-Location $root
    try {
        & docker compose --env-file .env.docker -f compose.yaml --profile quality @ComposeArguments
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
} finally {
    if ($acquired) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}

exit $exitCode
