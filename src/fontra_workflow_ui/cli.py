"""``fontra-workflow-ui``: the action catalog and recipe checks, from the
command line.

    fontra-workflow-ui list-actions [--json] [--type filter]
    fontra-workflow-ui validate recipe.yaml [--substitute key:value] [--json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import textwrap

import yaml

from .introspect import ACTION_TYPES, Catalog, buildCatalog
from .validate import describeSchema, validateRecipe


def listActions(catalog: Catalog, *, asJSON: bool, actionType: str | None) -> str:
    if asJSON:
        data = catalog.toJSON()
        if actionType is not None:
            data["actions"] = {actionType: data["actions"][actionType]}
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    lines: list[str] = []
    for type_ in ACTION_TYPES:
        if actionType is not None and type_ != actionType:
            continue
        actions = catalog.actions.get(type_, {})
        lines.append(f"{type_} actions ({len(actions)})")
        lines.append("")
        for name, info in sorted(actions.items()):
            package = f"  [{info.package}]" if info.package != "fontra" else ""
            lines.append(f"  {name}{package}")
            if info.description:
                lines += textwrap.wrap(
                    info.description,
                    width=78,
                    initial_indent="      ",
                    subsequent_indent="      ",
                )
            for argName, schema in info.properties.items():
                lines.append("      - " + _argumentLine(argName, schema, info))
            lines.append("")
    for error in catalog.loadErrors:
        lines.append(f"could not load {error['entryPoint']}: {error['error']}")
    return "\n".join(lines).rstrip() + "\n"


def _argumentLine(name: str, schema: dict, info) -> str:
    parts = [f"{name}: {describeSchema(schema)}"]
    if name in info.required:
        parts.append("required")
    elif "default" in schema:
        parts.append(f"default {json.dumps(schema['default'], ensure_ascii=False)}")
    if schema.get("format"):
        parts.append(schema["format"])  # "path", "hive-project"…
    return ", ".join(parts)


def _substitution(text: str) -> tuple[str, object]:
    key, sep, value = text.partition(":")
    if not sep:
        raise argparse.ArgumentTypeError(f"expected key:value, got {text!r}")
    return key, yaml.safe_load(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fontra-workflow-ui")
    commands = parser.add_subparsers(dest="command", required=True)

    listParser = commands.add_parser(
        "list-actions", help="list the workflow actions installed, with arguments"
    )
    listParser.add_argument(
        "--json", action="store_true", help="the catalog with JSON schemas"
    )
    listParser.add_argument("--type", choices=ACTION_TYPES, help="only this type")

    validateParser = commands.add_parser(
        "validate", help="check a recipe against the installed actions"
    )
    validateParser.add_argument("recipe", type=pathlib.Path)
    validateParser.add_argument(
        "--substitute",
        action="append",
        type=_substitution,
        default=None,
        help="a key:value substitution, as for fontra-workflow",
    )
    validateParser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    catalog = buildCatalog()

    if args.command == "list-actions":
        sys.stdout.write(listActions(catalog, asJSON=args.json, actionType=args.type))
        return 0

    text = args.recipe.read_text(encoding="utf-8")
    config = json.loads(text) if args.recipe.suffix == ".json" else yaml.safe_load(text)
    substitutions = dict(args.substitute) if args.substitute else None
    check = validateRecipe(config, catalog=catalog, substitutions=substitutions)
    if args.json:
        sys.stdout.write(json.dumps(check.toJSON(), indent=2) + "\n")
    else:
        for error in check.errors:
            print(error)
        if check.ok:
            variables = ", ".join(sorted(check.variables))
            print("ok" + (f" (variables: {variables})" if variables else ""))
    return 0 if check.ok else 1


if __name__ == "__main__":
    sys.exit(main())
