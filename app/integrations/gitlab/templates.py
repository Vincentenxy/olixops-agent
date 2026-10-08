"""Template provider abstraction and local GitLab fixture implementation."""

import json
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Protocol


@dataclass(frozen=True)
class TemplatePackage:
    template_id: str
    software_kind: str
    version: str
    commit_sha: str
    parameters_schema: dict[str, Any]
    manifest_template: str


class TemplateProvider(Protocol):
    def list_templates(self) -> list[TemplatePackage]: ...

    def get_template(self, template_id: str, commit_sha: str | None = None) -> TemplatePackage: ...


class LocalFixtureTemplateProvider:
    """Drop-in stand-in for GitLab Repository Files API during the first slice."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list_templates(self) -> list[TemplatePackage]:
        packages: list[TemplatePackage] = []
        for package_file in sorted(self.root.glob("catalog/**/package.json")):
            packages.append(self._read(package_file.parent))
        return packages

    def get_template(self, template_id: str, commit_sha: str | None = None) -> TemplatePackage:
        for package in self.list_templates():
            if package.template_id == template_id:
                if commit_sha is not None and package.commit_sha != commit_sha:
                    raise ValueError("template commit does not match fixture commit")
                return package
        raise KeyError(f"template not found: {template_id}")

    def _read(self, directory: Path) -> TemplatePackage:
        metadata = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        schema = json.loads((directory / str(metadata["schema_file"])).read_text(encoding="utf-8"))
        manifest = (directory / str(metadata["manifest_file"])).read_text(encoding="utf-8")
        return TemplatePackage(
            template_id=str(metadata["template_id"]),
            software_kind=str(metadata["software_kind"]),
            version=str(metadata["version"]),
            commit_sha=str(metadata["commit_sha"]),
            parameters_schema=schema,
            manifest_template=manifest,
        )


def render_redis(package: TemplatePackage, parameters: dict[str, Any]) -> str:
    if package.software_kind != "redis":
        raise ValueError("fixture renderer only supports redis")
    values = {
        "NAME": str(parameters["name"]),
        "NAMESPACE": str(parameters["namespace"]),
        "IMAGE": str(parameters.get("image", "redis:7.2-alpine")),
        "REPLICAS": str(parameters.get("replicas", 1)),
        "PORT": str(parameters.get("port", 6379)),
    }
    return Template(package.manifest_template).substitute(values)
