"""The agent's editable prompt in the central MLflow prompt registry, `dataagentbench.system`.

One prompt name for the eval agent; one prompt version per agent version (fingerprint).
The template is the version's editable text: `system.md`, then each dataset's notes
under a `## Notes · <dataset>` heading. The folder `agents/<name>/` stays the record;
the registry is the index, like every MLflow copy here. Registering is idempotent: a
version whose fingerprint is already registered returns that prompt version.
`dab promote` moves the `champion` alias.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mlflow import MlflowClient

from dab_bench.tracking.mlflow_log import PROJECT, _client_setup

if TYPE_CHECKING:
    from dab_bench.agent.versions import AgentVersion

PROMPT_NAME = "dataagentbench.system"
CHAMPION_ALIAS = "champion"


def template(version: AgentVersion) -> str:
    parts = [version.system_prompt.rstrip()]
    for ds, text in sorted(version.notes.items()):
        parts.append(f"## Notes · {ds}\n\n{text.strip()}")
    return "\n\n".join(parts) + "\n"


def registered(fingerprint: str) -> int | None:
    """The prompt version already registered for this agent fingerprint, if any."""
    client = MlflowClient()
    try:
        found = client.search_prompt_versions(PROMPT_NAME)
    except Exception:  # noqa: BLE001 - the prompt does not exist yet
        return None
    for pv in getattr(found, "prompt_versions", found) or []:
        if (pv.tags or {}).get("fingerprint") == fingerprint:
            return int(pv.version)
    return None


def register(version: AgentVersion) -> int:
    """Register `version`'s editable text as a prompt version (once per fingerprint)."""
    import mlflow.genai

    _client_setup()
    have = registered(version.fingerprint)
    if have is not None:
        return have
    pv = mlflow.genai.register_prompt(
        name=PROMPT_NAME,
        template=template(version),
        commit_message=f"{version.name} @ {version.fingerprint}",
        tags={
            "project": PROJECT,
            "agent": version.name,
            "fingerprint": version.fingerprint,
            "challenger_of": version.config.challenger_of or "",
        },
    )
    return int(pv.version)


def set_champion(prompt_version: int) -> None:
    import mlflow.genai

    _client_setup()
    mlflow.genai.set_prompt_alias(PROMPT_NAME, alias=CHAMPION_ALIAS, version=prompt_version)
