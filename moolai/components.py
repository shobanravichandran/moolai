"""Path -> Component resolution from config/components.yaml (longest prefix wins)."""

from dataclasses import dataclass
from fnmatch import fnmatch
from functools import cache

import yaml

from .config import CONFIG_DIR


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    team: str | None
    kind: str  # 'named' (from components.yaml) or 'dir' (fallback)


class Components:
    def __init__(self, spec: dict):
        self.repo: str = spec["repo"]
        self.skip: list[str] = spec.get("skip", [])
        self.named = [
            Component(c["id"], c["name"], c.get("team"), "named") for c in spec.get("components", [])
        ]
        self.aliases = {c["id"]: c.get("aliases", []) for c in spec.get("components", [])}
        by_id = {c.id: c for c in self.named}
        # Longest prefix first, so pkg/kubelet/cm/dra/ beats pkg/kubelet/.
        self.prefixes = sorted(
            ((p, by_id[c["id"]]) for c in spec.get("components", []) for p in c.get("paths", [])),
            key=lambda pc: len(pc[0]),
            reverse=True,
        )

    def skipped(self, path: str) -> bool:
        """Vendored and generated files never become File nodes."""
        name = path.rsplit("/", 1)[-1]
        for pattern in self.skip:
            if pattern.startswith("**/"):
                if fnmatch(name, pattern[3:]):
                    return True
            elif path.startswith(pattern):
                return True
        return False

    def resolve(self, path: str) -> Component:
        for prefix, component in self.prefixes:
            if path.startswith(prefix):
                return component
        parts = path.split("/")
        if parts[:3] == ["staging", "src", "k8s.io"] and len(parts) > 4:
            prefix = "/".join(parts[:4])  # staging/src/k8s.io/<module>
        elif len(parts) > 2:
            prefix = "/".join(parts[:2])  # pkg/volume
        elif len(parts) == 2:
            prefix = parts[0]
        else:
            prefix = "(root)"
        return Component(f"dir:{prefix}", prefix, None, "dir")


@cache
def load_components() -> Components:
    return Components(yaml.safe_load((CONFIG_DIR / "components.yaml").read_text(encoding="utf-8")))
