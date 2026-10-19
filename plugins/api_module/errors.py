"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/api_module/errors.py
Description: What an API provider's failure looks like to the rest of the
             server. Every text here is curated: it names the provider and
             the HTTP status, never the key, never the response body.

             What the core does with them is what they MEAN
             (`routing.classify`, C4.8 N5):
             * a refused key (401/403) says it is final (`fault`) and travels
               as an HTTPException (502: the SERVER is fine, the upstream said
               no; a 401 here would log the user out of the UI);
             * a limit, a balance, a 5xx, a provider that does not answer in
               time or cannot be reached is this engine failing at this
               moment. The API has no engine behind it, so the turn ends as a
               cascade with nobody left does: a 503 with the first failure.
             Every one carries `curated_text(lang)`, which the core's
             `curated_error_text` prefers over its generic sentence: the 503
             still names the provider and the reason.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from fastapi import HTTPException

_AUTH = {
    "ca": "{name} ha rebutjat la clau d'API. Comprova la clau al fitxer .env del servidor.",
    "es": "{name} ha rechazado la clave de API. Comprueba la clave en el archivo .env del servidor.",
    "en": "{name} rejected the API key. Check the key in the server's .env file.",
}
_BALANCE = {
    "ca": "{name} indica que el saldo del compte és insuficient.",
    "es": "{name} indica que el saldo de la cuenta es insuficiente.",
    "en": "{name} reports that the account balance is insufficient.",
}
_RATE = {
    "ca": "{name} ha limitat les peticions. Torna-ho a provar d'aquí a uns segons.",
    "es": "{name} ha limitado las peticiones. Inténtalo de nuevo en unos segundos.",
    "en": "{name} is rate limiting requests. Try again in a few seconds.",
}
_DOWN = {
    "ca": "{name} no està disponible ara mateix (HTTP {status}).",
    "es": "{name} no está disponible ahora mismo (HTTP {status}).",
    "en": "{name} is not available right now (HTTP {status}).",
}
_LATE = {
    "ca": "{name} no ha respost a temps.",
    "es": "{name} no ha respondido a tiempo.",
    "en": "{name} did not answer in time.",
}
_UNREACHABLE = {
    "ca": "No es pot connectar amb {name}.",
    "es": "No se puede conectar con {name}.",
    "en": "{name} cannot be reached.",
}
_REJECTED = {
    "ca": "{name} ha rebutjat la petició (HTTP {status}).",
    "es": "{name} ha rechazado la petición (HTTP {status}).",
    "en": "{name} rejected the request (HTTP {status}).",
}


def _say(table: dict, lang: "str | None", name: str, status: int) -> str:
    code = (lang or "ca")[:2]
    return table.get(code, table["en"]).format(name=name, status=status)


class ApiAuthError(HTTPException):
    """The provider refused the key (401/403). Terminal: no retry and no other
    engine changes a key the provider refuses (`fault`, read by the core)."""

    fault = "refused"

    def __init__(self, provider_name: str, upstream_status: int) -> None:
        self.provider_name = provider_name
        self.upstream_status = upstream_status
        super().__init__(status_code=502, detail=_say(_AUTH, "en", provider_name, upstream_status))

    def curated_text(self, lang: "str | None") -> str:
        return _say(_AUTH, lang, self.provider_name, self.upstream_status)


class ApiProviderError(Exception):
    """The provider could not serve this request now (402, 429, 5xx, a bad
    request, an error inside the stream). Not terminal for the cascade."""

    def __init__(self, provider_name: str, upstream_status: int) -> None:
        self.provider_name = provider_name
        self.upstream_status = upstream_status
        super().__init__(f"{provider_name} answered HTTP {upstream_status}")

    def curated_text(self, lang: "str | None") -> str:
        status = self.upstream_status
        if status == 402:
            table = _BALANCE
        elif status == 429:
            table = _RATE
        elif status >= 500:
            table = _DOWN
        else:
            table = _REJECTED
        return _say(table, lang, self.provider_name, status)


class ApiTimeout(TimeoutError):
    """The provider did not answer in time. Its text names the provider only."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"{provider_name} did not answer in time")

    def curated_text(self, lang: "str | None") -> str:
        return _say(_LATE, lang, self.provider_name, 0)


class ApiUnreachable(ConnectionError):
    """The provider cannot be reached. Its text names the provider only."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"{provider_name} is unreachable")

    def curated_text(self, lang: "str | None") -> str:
        return _say(_UNREACHABLE, lang, self.provider_name, 0)
