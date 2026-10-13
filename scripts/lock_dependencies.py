"""Pin installed dependency closures for runtime and development, without editable paths."""

import tomllib
from importlib.metadata import distribution
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def closure(requirements):
    found = {}
    pending = list(requirements)
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker:
            supported = False
            for platform in ("win32", "linux"):
                for version in ("3.11", "3.14"):
                    env = default_environment() | {
                        "sys_platform": platform,
                        "python_version": version,
                        "extra": "",
                    }
                    supported |= requirement.marker.evaluate(env)
            if not supported:
                continue
        name = canonicalize_name(requirement.name)
        if name in found:
            continue
        package = distribution(name)
        found[name] = f"{package.metadata['Name']}=={package.version}"
        pending.extend(package.requires or [])
    return sorted(found.values(), key=str.lower)


def main():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for filename, requirements in (
        ("requirements.runtime.lock", project["dependencies"]),
        ("requirements.lock", project["dependencies"] + project["optional-dependencies"]["dev"]),
    ):
        rows = closure(requirements)
        (root / filename).write_text(
            "# Installed dependency pins. Regenerate with scripts/lock_dependencies.py.\n"
            "# Install project separately: python -m pip install --no-deps -e .\n"
            + "\n".join(rows)
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
