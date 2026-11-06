"""
Caracterização do acesso atual (Plano de Evolução, Fase 0 PR 4): qual guarda protege cada rota.

O mapa em ``route_access_snapshot.json`` é a foto de HOJE. Qualquer mudança de permissão de uma rota (PRs de
catálogo, desmembramento e contexto de acesso) faz este teste falhar até o mapa ser regenerado de propósito:

    cd backend && uv run python -m tests.access_control.test_route_access_snapshot

e o diff do JSON entrar na revisão do PR. Rotas novas também aparecem no diff.

Legenda de cada rota (pode haver mais de uma, separadas por " + "):
  sem token            nenhuma dependência de autenticação JWT (públicas, webhooks com segredo próprio, health)
  token                JWT válido de usuário ativo, sem permissão específica na dependência
  perm:X               ``require_permission("X")`` (administrador passa, exceto nas críticas)
  qualquer:X|Y         ``require_any_permission("X", "Y")`` (administrador sempre passa)
  (crítica)            permissão crítica: o administrador só passa com concessão individual
  regras no handler    a decisão também depende de código dentro da rota/serviço (perfil técnico, setor,
                       solicitante, dono do ativo); coberta pelos testes de comportamento deste pacote
"""

import json
import sys
from pathlib import Path

from fastapi.routing import APIRoute, APIWebSocketRoute

from app.identity.permission_catalog import is_critical
from app.main import app

SNAPSHOT = Path(__file__).with_name("route_access_snapshot.json")

# Dependências que levam a decisão para dentro da rota.
_HANDLER_RULES = {"get_access_context", "get_token_payload"}


def _closure_value(call, name: str):
    code = getattr(call, "__code__", None)
    if code is None or name not in code.co_freevars:
        return None
    return call.__closure__[code.co_freevars.index(name)].cell_contents


def _guards(dependant, found: set[str]) -> None:
    for dep in dependant.dependencies:
        call = dep.call
        name = getattr(call, "__name__", type(call).__name__)
        if name == "_require_permission":
            found.add(f"perm:{_closure_value(call, 'required_permission')}")
        elif name == "_require_any_permission":
            found.add("qualquer:" + "|".join(_closure_value(call, "required_permissions")))
        else:
            if name in ("get_token_payload", "get_current_user_id"):
                found.add("token")
            if name in _HANDLER_RULES and dependant.call is not None and dependant.call.__name__ not in (
                "_require_permission",
                "_require_any_permission",
                "get_current_user_id",
            ):
                found.add("regras no handler")
            _guards(dep, found)


def _iter_routes(routes, prefix: str = ""):
    """Rotas com o caminho completo. FastAPI >= 0.142 guarda cada include_router como um nó com o router original."""
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            assert not route.include_context.dependencies, "dependências no include_router: incluir no mapa"
            yield from _iter_routes(included.routes, prefix + route.include_context.prefix)
        else:
            yield prefix + getattr(route, "path", ""), route


def _mark_critical(guard: str) -> str:
    """Crítica: o administrador não passa sem concessão individual (PR 5)."""
    kind, codes = guard.split(":", 1)
    return kind + ":" + "|".join(f"{c} (crítica)" if is_critical(c) else c for c in codes.split("|"))


def route_access_map() -> dict[str, str]:
    result: dict[str, str] = {}
    for path, route in _iter_routes(app.routes):
        if isinstance(route, APIRoute):
            methods = sorted(route.methods - {"HEAD", "OPTIONS"})
        elif isinstance(route, APIWebSocketRoute):
            methods = ["WS"]
        else:
            continue
        found: set[str] = set()
        _guards(route.dependant, found)
        if methods == ["WS"]:
            found.add("regras no handler")  # o WebSocket valida o ticket de curta duração dentro da rota
        perms = sorted(_mark_critical(g) for g in found if g.startswith(("perm:", "qualquer:")))
        parts = perms or (["token"] if "token" in found else ["sem token"])
        if "regras no handler" in found:
            parts.append("regras no handler")
        for method in methods:
            result[f"{method} {path}"] = " + ".join(parts)
    return dict(sorted(result.items()))


def test_route_access_matches_the_characterized_snapshot():
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current = route_access_map()
    changed = {k: (expected.get(k), current.get(k)) for k in expected.keys() | current.keys() if expected.get(k) != current.get(k)}
    assert not changed, (
        "Acesso de rotas mudou (antes, agora). Se foi intencional, regenere o mapa "
        "(uv run python -m tests.access_control.test_route_access_snapshot) e explique no PR:\n"
        + "\n".join(f"  {k}: {v[0]!r} -> {v[1]!r}" for k, v in sorted(changed.items()))
    )


def test_every_route_that_writes_requires_a_token_except_the_known_public_ones():
    """Escrita sem token só nas rotas públicas conhecidas (login, setup, recuperação de senha e webhooks)."""
    public_writes = [
        k for k, v in route_access_map().items() if v == "sem token" and k.split(" ", 1)[0] in ("POST", "PUT", "PATCH", "DELETE")
    ]
    for route in public_writes:
        assert any(word in route for word in ("/identity/", "/integrations/", "webhook", "/setup")), route


if __name__ == "__main__":
    SNAPSHOT.write_text(json.dumps(route_access_map(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{SNAPSHOT} atualizado ({len(route_access_map())} rotas)", file=sys.stderr)
