import dataclasses
import enum
from typing import Any

import pytest

from fontra_workflow_ui import introspect
from fontra_workflow_ui.introspect import (
    ACTION_TYPES,
    actionRegistry,
    bundledDescriptions,
    buildCatalog,
    describeAction,
    parseDocstring,
    typeSchema,
)


@pytest.fixture(scope="module")
def catalog():
    return buildCatalog()


def upstreamActions(catalog):
    return [info for info in catalog if info.package == "fontra"]


def test_registry_loads_without_errors(catalog):
    assert catalog.loadErrors == []
    assert catalog.fontraVersion


def test_every_registered_action_has_a_schema(catalog):
    registry = actionRegistry()
    for actionType in ACTION_TYPES:
        assert set(catalog.actions[actionType]) == set(registry[actionType])
    for info in catalog:
        schema = info.arguments
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema.get("required", [])) <= set(schema["properties"])
        # every argument maps to JSON types: nothing left as "x-python-type"
        assert info.unmappedArguments == [], (info.name, info.unmappedArguments)


def test_upstream_actions_are_all_there(catalog):
    names = {(info.actionType, info.name) for info in upstreamActions(catalog)}
    # a few that must always be found; the full list is the registry's
    for expected in [
        ("input", "fontra-read"),
        ("output", "fontra-write"),
        ("filter", "subset-glyphs"),
        ("filter", "instantiate"),
        ("filter", "scale"),
    ]:
        assert expected in names
    assert len(names) >= 40


def test_engine_fields_are_not_arguments(catalog):
    assert "input" not in catalog.get("output", "fontra-write").properties


def test_every_action_has_a_description(catalog):
    """Fails when Fontra (or an installed package) adds an action or an
    argument that is not described: add it to descriptions.yaml."""
    missing = []
    for info in catalog:
        if not info.description:
            missing.append(f"{info.actionType} {info.name}")
        for name, schema in info.properties.items():
            if not schema.get("description"):
                missing.append(f"{info.actionType} {info.name}: {name}")
    assert missing == [], "no description for:\n" + "\n".join(missing)


def test_descriptions_file_has_no_stale_entries(catalog):
    """Fails when an action or argument described in descriptions.yaml no
    longer exists (renamed or removed upstream)."""
    from importlib.metadata import PackageNotFoundError, version

    stale = []
    for actionType, actions in bundledDescriptions().items():
        for name, entry in actions.items():
            package = entry.get("package")
            if package:
                try:
                    version(package)
                except PackageNotFoundError:
                    continue  # an optional package that is not installed
            info = catalog.get(actionType, name)
            if info is None:
                stale.append(f"{actionType} {name}")
                continue
            for argument in entry.get("arguments") or {}:
                if argument not in info.properties:
                    stale.append(f"{actionType} {name}: {argument}")
    assert stale == [], "described but not found:\n" + "\n".join(stale)


def test_defaults_and_required(catalog):
    scale = catalog.get("filter", "scale")
    assert scale.required == ["scaleFactor"]
    assert scale.properties["scaleFactor"]["type"] == "number"
    assert scale.properties["scaleKerning"] == {
        "type": "boolean",
        "default": True,
        "description": scale.properties["scaleKerning"]["description"],
    }
    subset = catalog.get("filter", "subset-glyphs")
    assert subset.required == []
    assert subset.properties["glyphNames"]["default"] == []  # a set, as a list
    assert subset.properties["glyphNames"]["items"] == {"type": "string"}


def test_enumerations(catalog):
    # an Enum annotation
    trim = catalog.get("filter", "trim-variable-glyphs")
    assert trim.properties["moveDefaultBehavior"]["enum"] == ["none", "empty", "any"]
    assert trim.properties["moveDefaultBehavior"]["default"] == "any"
    # a str annotation whose default is an Enum member
    layout = catalog.get("filter", "subset-glyphs").properties["layoutHandling"]
    assert layout["enum"] == ["subset", "closure", "ignore"]
    assert layout["default"] == "subset"


def test_path_arguments(catalog):
    assert catalog.get("input", "fontra-read").isPathArgument("source")
    assert catalog.get("output", "fontra-write").isPathArgument("destination")
    subset = catalog.get("filter", "subset-glyphs")
    assert subset.isPathArgument("glyphNamesFile")
    assert not subset.isPathArgument("glyphNames")
    # a boolean called "...Path" is not a path
    assert not catalog.get("filter", "drop-shapes").isPathArgument("dropPath")


def test_catalog_json(catalog):
    data = catalog.toJSON()
    assert data["schemaVersion"] == introspect.SCHEMA_VERSION
    assert data["stepTypes"] == ["input", "filter", "output", "fork", "fork-merge"]
    names = [a["name"] for a in data["actions"]["filter"]]
    assert names == sorted(names)
    entry = next(a for a in data["actions"]["filter"] if a["name"] == "scale")
    assert entry["package"] == "fontra"
    assert entry["module"].startswith("fontra.workflow.actions")


def test_schemas_are_valid_json_schema(catalog):
    jsonschema = pytest.importorskip("jsonschema")
    validator = getattr(jsonschema, "Draft202012Validator", None)
    if validator is None:
        pytest.skip("jsonschema without draft 2020-12")
    for info in catalog:
        validator.check_schema(info.arguments)


def test_fontra_compile_actions_when_installed(catalog):
    pytest.importorskip("fontra_compile")
    for name in ["compile-fontmake", "compile-fontc", "compile-varc"]:
        info = catalog.get("output", name)
        assert info is not None
        assert info.package == "fontra-compile"
        assert info.required == ["destination"]


# --- the generic parts, on made-up types and actions -------------------------------


class Color(enum.Enum):
    red = "red"
    blue = "blue"


@pytest.mark.parametrize(
    "annotation, expected",
    [
        (str, {"type": "string"}),
        (bool, {"type": "boolean"}),
        (int, {"type": "integer"}),
        (float, {"type": "number"}),
        (Any, {}),
        (str | None, {"type": ["string", "null"]}),
        (list[int], {"type": "array", "items": {"type": "integer"}}),
        (set[str], {"type": "array", "items": {"type": "string"}}),
        (
            dict[str, float],
            {
                "type": "object",
                "propertyNames": {"type": "string"},
                "additionalProperties": {"type": "number"},
            },
        ),
        (
            tuple[str, str],
            {
                "type": "array",
                "prefixItems": [{"type": "string"}, {"type": "string"}],
                "minItems": 2,
                "maxItems": 2,
            },
        ),
        (tuple[int, ...], {"type": "array", "items": {"type": "integer"}}),
        (Color, {"type": "string", "enum": ["red", "blue"]}),
        (
            list[str] | None,
            {
                "anyOf": [
                    {"type": "array", "items": {"type": "string"}},
                    {"type": "null"},
                ]
            },
        ),
    ],
)
def test_type_schema(annotation, expected):
    assert typeSchema(annotation) == expected


def test_unknown_type_is_kept_as_python_type():
    class Thing:
        pass

    schema = typeSchema(Thing)
    assert list(schema) == ["x-python-type"]
    assert schema["x-python-type"].endswith("Thing")


def test_docstring_wins_over_descriptions_file():
    @dataclasses.dataclass(kw_only=True)
    class Documented:
        """Do a thing to every glyph.

        Arguments:
            amount: How much of it.
              Continued here.
            color: Which color.
        """

        amount: float
        color: Color = Color.red

    descriptions = {
        "filter": {
            "documented": {
                "description": "from the file",
                "arguments": {"amount": "file amount", "color": "file color"},
            }
        }
    }
    info = describeAction("filter", "documented", Documented, descriptions)
    assert info.description == "Do a thing to every glyph."
    assert info.descriptionSource == "docstring"
    assert info.properties["amount"]["description"] == "How much of it. Continued here."
    assert info.properties["color"]["description"] == "Which color."
    assert info.properties["color"]["default"] == "red"
    assert info.required == ["amount"]


def test_descriptions_file_is_the_fallback():
    @dataclasses.dataclass(kw_only=True)
    class Undocumented:
        amount: float = 1.0

    descriptions = {
        "filter": {
            "undocumented": {
                "description": "From the file.",
                "arguments": {"amount": "File amount."},
            }
        }
    }
    info = describeAction("filter", "undocumented", Undocumented, descriptions)
    # @dataclass makes up a docstring from the signature: not a description
    assert Undocumented.__doc__.startswith("Undocumented(")
    assert info.description == "From the file."
    assert info.descriptionSource == "descriptions.yaml"
    assert info.properties["amount"]["description"] == "File amount."


def test_parse_docstring_without_arguments():
    assert parseDocstring("One line.") == ("One line.", {})
    assert parseDocstring(None) == (None, {})


def test_a_type_can_give_its_own_schema():
    class ProjectRef(str):
        __json_schema__ = {"type": "string", "format": "some-project"}

    schema = typeSchema(ProjectRef)
    assert schema == {"type": "string", "format": "some-project"}
    schema["format"] = "changed"  # a copy, not the class's own dict
    assert ProjectRef.__json_schema__["format"] == "some-project"
    assert typeSchema(ProjectRef | None) == {
        "anyOf": [{"type": "string", "format": "some-project"}, {"type": "null"}]
    }
