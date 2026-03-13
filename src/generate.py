"""
generate.py

Reads config.yaml, collects dependency information from each package's package.json,
and generates dependency.md (Mermaid graph + detail table).

Usage:
    python generate.py
    python generate.py --config config.yaml --output dependency.md
"""

import json
import argparse
from pathlib import Path
import yaml  # pip install pyyaml


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_package_json(folder: Path) -> Path | None:
    """Returns package.json directly under the folder, or None if not found."""
    p = folder / "package.json"
    return p if p.exists() else None


def collect_packages(config: dict, config_dir: Path) -> list[dict]:
    """Collects all package information from the packages section of config.yaml."""
    packages = []
    for entry in config.get("packages", []):
        root = Path(entry["root"])
        for dir_name in entry.get("dirs", []):
            folder = root / dir_name
            pkg_json_path = find_package_json(folder)
            if pkg_json_path is None:
                print(f"[WARN] package.json not found: {folder}")
                continue
            with pkg_json_path.open(encoding="utf-8") as f:
                data = json.load(f)
            packages.append({
                "id":          data.get("name", ""),
                "display":     data.get("displayName", data.get("name", "")),
                "version":     data.get("version", ""),
                "description": data.get("description", ""),
                "dependencies": data.get("dependencies", {}),  # {id: version}
            })
    return packages


# ---------------------------------------------------------------------------
# External package display names
# ---------------------------------------------------------------------------

def auto_display(pkg_id: str) -> str:
    """Converts the last segment of a package ID to title case to generate a display name.
    e.g. com.unity.nuget.newtonsoft-json -> Newtonsoft Json
    """
    last = pkg_id.split(".")[-1]
    return last.replace("-", " ").title()


def resolve_display(pkg_id: str, external_config: dict) -> str:
    """Uses the display name from the external section if available, otherwise auto-generates."""
    entry = external_config.get(pkg_id)
    if entry and entry.get("display"):
        return entry["display"]
    return auto_display(pkg_id)


# ---------------------------------------------------------------------------
# Mermaid generation
# ---------------------------------------------------------------------------

def mermaid_id(pkg_id: str) -> str:
    """Converts a package ID to a string usable as a Mermaid node ID."""
    return pkg_id.replace(".", "_").replace("-", "_")


def build_mermaid(own_packages: list[dict], external_ids: set[str], external_config: dict) -> str:
    lines = ["```mermaid", "graph TD"]

    # Node definitions
    lines.append("")
    lines.append("    %% Own packages")
    for p in own_packages:
        mid = mermaid_id(p["id"])
        label = p["display"] or p["id"]
        lines.append(f'    {mid}["{label}"]')

    if external_ids:
        lines.append("")
        lines.append("    %% External packages")
        for ext_id in sorted(external_ids):
            mid = mermaid_id(ext_id)
            label = resolve_display(ext_id, external_config)
            lines.append(f'    {mid}(["{label}"])')

    # Edges
    lines.append("")
    lines.append("    %% Dependencies")
    for p in own_packages:
        src = mermaid_id(p["id"])
        for dep_id in p["dependencies"]:
            dst = mermaid_id(dep_id)
            lines.append(f"    {src} --> {dst}")

    # Styles
    own_mids   = ",".join(mermaid_id(p["id"]) for p in own_packages)
    ext_mids   = ",".join(mermaid_id(e) for e in sorted(external_ids))

    lines.append("")
    lines.append("    classDef own      fill:#4a90d9,stroke:#2c5f8a,color:#fff")
    lines.append("    classDef external fill:#7a7a7a,stroke:#555,color:#fff")
    if own_mids:
        lines.append(f"    class {own_mids} own")
    if ext_mids:
        lines.append(f"    class {ext_mids} external")

    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def build_details(own_packages: list[dict], external_ids: set[str], external_config: dict) -> str:
    own_ids   = {p["id"] for p in own_packages}
    own_disp  = {p["id"]: (p["display"] or p["id"]) for p in own_packages}

    # Build reverse dependency map
    depended_by: dict[str, list[str]] = {p["id"]: [] for p in own_packages}
    for p in own_packages:
        for dep_id in p["dependencies"]:
            if dep_id in depended_by:
                depended_by[dep_id].append(p["display"] or p["id"])

    sections = []
    for p in own_packages:
        dep_list = []
        for dep_id, dep_ver in p["dependencies"].items():
            label = own_disp.get(dep_id) or resolve_display(dep_id, external_config)
            dep_list.append(f"{label} `{dep_ver}`")
        deps_str     = ", ".join(dep_list) if dep_list else "None"
        depended_str = ", ".join(depended_by[p["id"]]) if depended_by[p["id"]] else "None"

        sections.append(f"### {p['display']} `v{p['version']}`\n")
        sections.append("| Field | Value |")
        sections.append("|---|---|")
        sections.append(f"| Description | {p['description'] or '—'} |")
        sections.append(f"| Dependencies | {deps_str} |")
        sections.append(f"| Depended by | {depended_str} |")
        sections.append("")

    return "\n".join(sections)


def build_markdown(own_packages: list[dict], external_ids: set[str], external_config: dict, rules: list[str]) -> str:
    mermaid_block = build_mermaid(own_packages, external_ids, external_config)
    details_block = build_details(own_packages, external_ids, external_config)

    legend = (
        "**Legend**\n"
        "- 🔵 Blue: Own packages\n"
        "- ⬛ Gray: External packages (UPM / third-party)\n"
    )

    rules_block = ""
    if rules:
        rules_block = "## Dependency Rules\n\n"
        rules_block += "\n".join(f"- {r}" for r in rules)

    return f"""# Unity Package Dependency Map

## Dependency Graph

{mermaid_block}

{legend}
---

## Package Details

{details_block}
---

{rules_block}
""".strip() + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--output", default="dependency.md")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)

    # Use the script's directory as the base
    script_dir = Path(__file__).parent
    if not config_path.is_absolute():
        config_path = script_dir / config_path
    if not output_path.is_absolute():
        output_path = script_dir / output_path

    config = load_config(config_path)
    own_packages = collect_packages(config, script_dir)

    own_ids = {p["id"] for p in own_packages}
    external_ids: set[str] = set()
    for p in own_packages:
        for dep_id in p["dependencies"]:
            if dep_id not in own_ids:
                external_ids.add(dep_id)

    external_config = config.get("external") or {}
    rules = config.get("rules", [])

    md = build_markdown(own_packages, external_ids, external_config, rules)
    output_path.write_text(md, encoding="utf-8")
    print(f"Generated: {output_path}")
    print(f"  Own packages: {len(own_packages)}")
    print(f"  External packages: {len(external_ids)}")


if __name__ == "__main__":
    main()
