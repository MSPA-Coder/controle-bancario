"""Rótulos de apresentação da trilha de auditoria.

A trilha grava códigos de máquina (`auth_login`, `delete`, `success`), nomes de
tabela (`account_month_close`) e um resumo escrito no momento do registro. Nada
disso se traduz no armazenamento: o que muda é o que a tela mostra. Cada mapa
leva o código ao rótulo em português, marcado com `gettext_noop` (o texto do
dicionário é a chave; o idioma entra só na saída, em `rotulo_*`).

Código sem rótulo aparece como foi gravado: um valor novo nunca some da tela
nem quebra a página; só fica sem rótulo até entrar no mapa.

Os resumos fixos foram gravados no idioma de quem agiu, então o mesmo texto
existe no banco em português e em inglês ("Entrada no sistema." e "Signed in.").
`rotulo_resumo` reconhece as duas formas e mostra a do idioma de quem lê.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from functools import lru_cache

from django.utils.translation import gettext, gettext_noop, override

#: Entidade (tabela ou conceito) gravada em `entity_name`.
ENTIDADES: dict[str, str] = {
    "account_month_close": gettext_noop("Fechamento mensal"),
    "account_owner": gettext_noop("Titular"),
    "account_source": gettext_noop("Fonte do saldo da conta"),
    "app_user": gettext_noop("Usuário"),
    "app_user_owner_access": gettext_noop("Acesso do usuário a titulares"),
    "app_user_permissions": gettext_noop("Permissões do usuário"),
    "app_user_transfer_destination_access": gettext_noop("Destinos de transferência do usuário"),
    "audit_log": gettext_noop("Trilha de auditoria"),
    "auth_login": gettext_noop("Acesso ao sistema"),
    "bank_operation": gettext_noop("Operação"),
    "bank_statement_import": gettext_noop("Importação de extrato"),
    "bank_statement_line": gettext_noop("Linha de extrato"),
    "cash_flow_category": gettext_noop("Categoria"),
    "cash_flow_category_group": gettext_noop("Grupo de categorias"),
    "cash_flow_entry": gettext_noop("Lançamento"),
    "entry_attachment": gettext_noop("Comprovante"),
    "financial_account": gettext_noop("Conta"),
    "financial_institution": gettext_noop("Instituição"),
    "monthly_budget": gettext_noop("Orçamento mensal"),
    "statement_rule": gettext_noop("Regra de extrato"),
}

#: Ação ou evento gravado em `action`.
ACOES: dict[str, str] = {
    "archived": gettext_noop("Arquivou"),
    "assign_responsible": gettext_noop("Atribuiu responsável"),
    "close": gettext_noop("Fechou o mês"),
    "create": gettext_noop("Criou"),
    "delete": gettext_noop("Excluiu"),
    "deleted": gettext_noop("Removeu"),
    "failed": gettext_noop("Tentativa de login recusada"),
    "ignore": gettext_noop("Ignorou"),
    "login": gettext_noop("Entrou no sistema"),
    "logout": gettext_noop("Saiu do sistema"),
    "password_reset": gettext_noop("Redefiniu a senha"),
    "profile_apply": gettext_noop("Aplicou perfil de permissões"),
    "realize": gettext_noop("Realizou"),
    "reconcile": gettext_noop("Conciliou"),
    "reopen": gettext_noop("Reabriu o mês"),
    "throttled": gettext_noop("Login bloqueado por tentativas"),
    "undo": gettext_noop("Desfez"),
    "undo_reconciliation": gettext_noop("Desfez a conciliação"),
    "unrealize": gettext_noop("Desfez a realização"),
    "update": gettext_noop("Alterou"),
}

#: Resultado gravado em `result`.
RESULTADOS: dict[str, str] = {
    "failure": gettext_noop("Falha"),
    "success": gettext_noop("Sucesso"),
}

#: Resumos que o código grava, em português. `%(nome)s` marca o pedaço que varia.
#: A lista é a dos textos fixos de `log_audit_event(summary=...)`; resumo livre,
#: com nomes e valores embutidos, não entra e aparece como foi gravado.
RESUMOS: tuple[str, ...] = (
    gettext_noop("Entrada no sistema."),
    gettext_noop("Saída do sistema."),
    gettext_noop("Usuário ou senha inválidos. Usuário informado: %(nome)s."),
    gettext_noop("Bloqueio de login acionado. Usuário informado: %(nome)s."),
    gettext_noop("Operação recusada pela validação do servidor."),
    gettext_noop("Fechamento mensal recusado pela validação do servidor."),
    gettext_noop("Reabertura mensal recusada pela validação do servidor."),
    gettext_noop("Fechamento mensal %(mes)s da conta #%(conta)s."),
    gettext_noop("Fechamento mensal %(mes)s da conta #%(conta)s reaberto."),
    gettext_noop("Lançamento criado."),
    gettext_noop("Lançamento editado (escopo: %(escopo)s)."),
    gettext_noop("Lançamento excluído (escopo: %(escopo)s)."),
    gettext_noop("Lançamento marcado como realizado."),
    gettext_noop("Lançamento retornado para vencidos."),
    gettext_noop("Ocorrência recorrente além do horizonte de projeção (%(fim)s) removida."),
    gettext_noop("Importação desfeita: %(linhas)s linhas removidas, %(conciliadas)s conciliações revertidas."),
    gettext_noop("%(n)s linhas ignoradas em lote."),
    gettext_noop("Lançamento movido de conta por ajuste de dados."),
    gettext_noop("Lançamento convertido em ponta de transferência por ajuste de dados."),
    gettext_noop("Ponta de transferência criada por ajuste de dados."),
    gettext_noop("Lançamento transformado em ponta de transferência a partir do extrato."),
    gettext_noop("Ponta de transferência criada a partir do extrato."),
    gettext_noop("Par de lançamentos próprios convertido em transferência."),
    gettext_noop("Marcação a mercado reclassificada como variação de mercado."),
    gettext_noop("Categoria reclassificada em lote."),
    gettext_noop("Fonte do saldo da conta alterada."),
    gettext_noop("Matriz de destinos completada a partir do histórico de transferências."),
    gettext_noop("Status da operação recalculado a partir das ocorrências."),
    gettext_noop("Rótulo de transferência refeito pelo nome atual da conta."),
    gettext_noop("Conciliação: realização corrigida pela data e valor do extrato."),
)


def _rotulo(mapa: dict[str, str], codigo) -> str:
    """Rótulo de `codigo` no idioma ativo; sem rótulo, o próprio código."""
    texto = "" if codigo is None else str(codigo)
    msgid = mapa.get(texto)
    return gettext(msgid) if msgid else texto


def rotulo_entidade(codigo) -> str:
    return _rotulo(ENTIDADES, codigo)


def rotulo_acao(codigo) -> str:
    return _rotulo(ACOES, codigo)


def rotulo_resultado(codigo) -> str:
    return _rotulo(RESULTADOS, codigo)


def opcoes_de_filtro(codigos: Iterable[str], rotulo: Callable[[str], str]) -> list[tuple[str, str]]:
    """Pares (código, rótulo) ordenados pelo rótulo exibido.

    O código segue como `value` do filtro; só o texto da opção muda.
    """
    pares = [(codigo, rotulo(codigo)) for codigo in codigos]
    return sorted(pares, key=lambda par: (par[1].casefold(), par[0]))


@lru_cache(maxsize=1)
def _reconhecedores() -> tuple[tuple[re.Pattern[str], str], ...]:
    """Um padrão por forma conhecida de cada resumo (português e inglês).

    A forma em inglês é a que o catálogo dá ao `msgid`: foi o que ficou gravado
    quando quem agiu usava a interface em inglês.
    """
    padroes: list[tuple[int, re.Pattern[str], str]] = []
    for msgid in RESUMOS:
        formas = {msgid}
        with override("en"):
            formas.add(gettext(msgid))
        for forma in formas:
            partes = re.split(r"%\((\w+)\)s", forma)
            regex = "".join(
                re.escape(parte) if indice % 2 == 0 else f"(?P<{parte}>.+?)"
                for indice, parte in enumerate(partes)
            )
            fixo = sum(len(parte) for indice, parte in enumerate(partes) if indice % 2 == 0)
            padroes.append((fixo, re.compile(rf"\A{regex}\Z", re.DOTALL), msgid))
    # O mais específico primeiro: "...da conta #%(conta)s." também casaria com
    # o texto de "...da conta #%(conta)s reaberto.".
    padroes.sort(key=lambda item: -item[0])
    return tuple((padrao, msgid) for _, padrao, msgid in padroes)


def rotulo_resumo(texto) -> str:
    """Resumo gravado, mostrado no idioma de quem lê quando o texto é conhecido.

    Texto que não bate com nenhum resumo conhecido sai como foi gravado.
    """
    original = "" if texto is None else str(texto)
    if not original:
        return ""
    # Um resumo antigo foi gravado sem o ponto final; o `msgid` o tem.
    candidatos = (original,) if original.endswith(".") else (original, original + ".")
    for candidato in candidatos:
        for padrao, msgid in _reconhecedores():
            achado = padrao.match(candidato)
            if achado:
                try:
                    return gettext(msgid) % achado.groupdict()
                except (KeyError, ValueError, TypeError):
                    return original
    return original
