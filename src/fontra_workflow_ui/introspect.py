"""The action catalog of ``fontra-workflow``, generated at run time.

Nothing here is written by hand per action: the catalog is read from Fontra's
action registry (``fontra.workflow.actions._actionRegistry``) after loading the
actions of every installed package (``fontra.workflow.actions`` entry points,
fontra-compile included when it is installed), and each action's arguments
come from ``dataclasses.fields()`` of its class. When Fontra renames an
argument or adds an action, the catalog follows without a change here.

Each action gets a JSON schema (draft 2020-12 vocabulary) for its arguments:
type, default, required or not, enumerations, and descriptions. Descriptions
come from the action's docstring when it has one, else from
``descriptions.yaml`` in this package.

Two extensions to JSON schema are used:

* ``"format": "path"`` marks an argument that names a file or folder (a
  string argument called ``source``, ``destination`` or ending in ``File``,
  ``Dir`` or ``Path``). A hosted runner refuses or rewrites those.
* A type may give its own schema with a ``__json_schema__`` dict (for
  instance ``{"type": "string", "format": "hive-project"}``), so that an
  argument naming something specific is told apart from any string.
* ``"x-python-type"`` keeps the Python annotation an argument was derived
  from, when it could not be mapped to a JSON type (the schema is then ``{}``,
  anything goes).
"""

from __future__ import annotations

import copy
import dataclasses
import enum
import inspect
import logging
import sys
import types
import typing
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from importlib.metadata import entry_points, packages_distributions, version
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

ACTION_TYPES = ("input", "filter", "output")
# Step types that hold nested steps and take no action name nor arguments.
STRUCTURAL_STEP_TYPES = ("fork", "fork-merge")
STEP_TYPES = ACTION_TYPES + STRUCTURAL_STEP_TYPES

ENTRY_POINT_GROUP = "fontra.workflow.actions"

# Fields of action classes that are set by the engine, not by a recipe.
_ENGINE_FIELDS = frozenset({"input"})

_PATH_NAMES = frozenset({"source", "destination"})
_PATH_SUFFIXES = ("File", "Dir", "Path")


@dataclass
class ActionInfo:
    actionType: str
    name: str
    cls: type
    package: str | None
    description: str | None
    descriptionSource: str | None  # "docstring", "descriptions.yaml" or None
    arguments: dict[str, Any]  # the JSON schema of the arguments object
    unmappedArguments: list[str] = field(default_factory=list)

    def toJSON(self) -> dict[str, Any]:
        return {
            "type": self.actionType,
            "name": self.name,
            "package": self.package,
            "module": self.cls.__module__,
            "class": self.cls.__qualname__,
            "description": self.description,
            "arguments": self.arguments,
        }

    @property
    def properties(self) -> dict[str, dict]:
        return self.arguments["properties"]

    @property
    def required(self) -> list[str]:
        return self.arguments.get("required", [])

    def isPathArgument(self, name: str) -> bool:
        return self.properties.get(name, {}).get("format") == "path"


@dataclass
class Catalog:
    actions: dict[str, dict[str, ActionInfo]]  # type -> name -> info
    loadErrors: list[dict[str, str]]
    fontraVersion: str | None

    def get(self, actionType: str, name: str) -> ActionInfo | None:
        return self.actions.get(actionType, {}).get(name)

    def __iter__(self):
        for actionType in ACTION_TYPES:
            yield from self.actions.get(actionType, {}).values()

    def toJSON(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "$schema": JSON_SCHEMA_DIALECT,
            "fontraVersion": self.fontraVersion,
            "stepTypes": list(STEP_TYPES),
            "actions": {
                actionType: [
                    info.toJSON()
                    for _, info in sorted(self.actions.get(actionType, {}).items())
                ]
                for actionType in ACTION_TYPES
            },
            "loadErrors": self.loadErrors,
        }


# --- loading the registry -------------------------------------------------------


def loadActions() -> list[dict[str, str]]:
    """Import Fontra's own actions and those of installed packages. Returns
    the entry points that could not be loaded (a broken plug-in package must
    not hide the others)."""
    from fontra.workflow import workflow

    try:
        workflow._loadActionsEntryPoints()
        return []
    except Exception:
        pass  # load what can be loaded, one entry point at a time

    errors = []
    for entryPoint in entry_points(group=ENTRY_POINT_GROUP):
        try:
            entryPoint.load()
        except Exception as error:
            logger.warning("cannot load %s: %r", entryPoint.value, error)
            errors.append({"entryPoint": entryPoint.value, "error": repr(error)})
    return errors


def actionRegistry() -> dict[str, dict[str, type]]:
    from fontra.workflow.actions import _actionRegistry

    return _actionRegistry


def buildCatalog() -> Catalog:
    """The catalog of every action the installed packages provide."""
    loadErrors = loadActions()
    descriptions = bundledDescriptions()
    actions: dict[str, dict[str, ActionInfo]] = {}
    for actionType in ACTION_TYPES:
        registry = actionRegistry().get(actionType, {})
        actions[actionType] = {
            name: describeAction(actionType, name, cls, descriptions)
            for name, cls in sorted(registry.items())
        }
    return Catalog(actions, loadErrors, _distributionVersion("fontra"))


# --- one action ---------------------------------------------------------------------


def describeAction(
    actionType: str, name: str, cls: type, descriptions: dict | None = None
) -> ActionInfo:
    if descriptions is None:
        descriptions = bundledDescriptions()
    bundled = descriptions.get(actionType, {}).get(name) or {}
    docSummary, docArguments = parseDocstring(_ownDocstring(cls))

    description, descriptionSource = None, None
    if docSummary:
        description, descriptionSource = docSummary, "docstring"
    elif bundled.get("description"):
        description = _clean(bundled["description"])
        descriptionSource = "descriptions.yaml"

    bundledArguments = bundled.get("arguments") or {}
    properties: dict[str, dict] = {}
    required: list[str] = []
    unmapped: list[str] = []

    for argName, annotation, default in _initArguments(cls):
        schema = typeSchema(annotation)
        if schema.get("x-python-type"):
            unmapped.append(argName)
        if default is not _NO_DEFAULT:
            if isinstance(default, enum.Enum) and "enum" not in schema:
                # e.g. ``layoutHandling: str = LayoutHandling.SUBSET``: the
                # enumeration is the default's class.
                schema["enum"] = [member.value for member in type(default)]
            try:
                schema["default"] = jsonValue(default)
            except TypeError:
                pass  # a default that has no JSON form: leave it out
        else:
            required.append(argName)
        if _isPathArgument(argName, schema):
            schema["format"] = "path"
        argDescription = docArguments.get(argName) or bundledArguments.get(argName)
        if argDescription:
            schema["description"] = _clean(argDescription)
        properties[argName] = schema

    arguments: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        arguments["required"] = required

    return ActionInfo(
        actionType=actionType,
        name=name,
        cls=cls,
        package=_packageOf(cls),
        description=description,
        descriptionSource=descriptionSource,
        arguments=arguments,
        unmappedArguments=unmapped,
    )


class _NoDefault:
    def __repr__(self):
        return "<no default>"


_NO_DEFAULT = _NoDefault()


def _initArguments(cls: type):
    """(name, annotation, default) for each argument a recipe may give."""
    if dataclasses.is_dataclass(cls):
        hints = _typeHints(cls)
        for f in dataclasses.fields(cls):
            if not f.init or f.name in _ENGINE_FIELDS:
                continue
            if f.default is not dataclasses.MISSING:
                default = f.default
            elif f.default_factory is not dataclasses.MISSING:
                default = f.default_factory()
            else:
                default = _NO_DEFAULT
            yield f.name, hints.get(f.name, Any), default
        return

    # Not a dataclass: the keyword parameters of its constructor.
    signature = inspect.signature(cls)
    hints = _typeHints(cls.__init__)
    for param in signature.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.name in _ENGINE_FIELDS:
            continue
        default = param.default if param.default is not param.empty else _NO_DEFAULT
        yield param.name, hints.get(param.name, Any), default


def _typeHints(obj) -> dict[str, Any]:
    try:
        return typing.get_type_hints(obj)
    except Exception:
        pass
    # One unresolvable annotation (an engine-only field, say) must not lose
    # the others: resolve them one by one, in the module that declared each.
    hints: dict[str, Any] = {}
    owners = obj.__mro__[::-1] if isinstance(obj, type) else [obj]
    for owner in owners:
        annotations = getattr(owner, "__annotations__", {})
        namespace = vars(sys.modules.get(owner.__module__, types.ModuleType("_")))
        for name, annotation in annotations.items():
            if isinstance(annotation, str):
                try:
                    annotation = eval(annotation, dict(namespace))  # noqa: S307
                except Exception:
                    annotation = _Unresolved(annotation)
            hints[name] = annotation
    return hints


@dataclass(frozen=True)
class _Unresolved:
    text: str


# --- types -> JSON schema ---------------------------------------------------------


_SIMPLE = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
    type(None): "null",
}


def typeSchema(annotation) -> dict[str, Any]:
    """The JSON schema of values of a Python annotation, as a recipe gives
    them (YAML: a ``set[str]`` is a list, a ``tuple`` is a list)."""
    if annotation is Any or annotation is typing.Any:
        return {}
    own = getattr(annotation, "__json_schema__", None)
    if isinstance(own, dict):
        # A type that says what it is (a project reference, say): tools can
        # tell it from any value of its JSON type.
        return copy.deepcopy(own)
    if annotation in _SIMPLE:
        return {"type": _SIMPLE[annotation]}
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        values = [member.value for member in annotation]
        schema: dict[str, Any] = {"enum": values}
        valueTypes = {_SIMPLE.get(type(v)) for v in values}
        if len(valueTypes) == 1 and None not in valueTypes:
            schema = {"type": valueTypes.pop(), "enum": values}
        return schema

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin is typing.Union or origin is types.UnionType:
        members = [typeSchema(arg) for arg in args]
        if all(set(m) == {"type"} and isinstance(m["type"], str) for m in members):
            return {"type": [m["type"] for m in members]}
        return {"anyOf": members}
    if origin is typing.Literal:
        return {"enum": list(args)}
    if annotation in (list, set, frozenset, tuple) or origin in (
        list,
        set,
        frozenset,
    ):
        schema = {"type": "array"}
        if args:
            schema["items"] = typeSchema(args[0])
        return schema
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": typeSchema(args[0])}
        return {
            "type": "array",
            "prefixItems": [typeSchema(arg) for arg in args],
            "minItems": len(args),
            "maxItems": len(args),
        }
    if annotation is dict or origin is dict:
        schema = {"type": "object"}
        if args:
            schema["propertyNames"] = typeSchema(args[0])
            schema["additionalProperties"] = typeSchema(args[1])
        return schema

    text = annotation.text if isinstance(annotation, _Unresolved) else annotation
    return {"x-python-type": _typeName(text)}


def _typeName(annotation) -> str:
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, type):
        return f"{annotation.__module__}.{annotation.__qualname__}"
    return repr(annotation)


def _isPathArgument(name: str, schema: dict) -> bool:
    if not (name in _PATH_NAMES or name.endswith(_PATH_SUFFIXES)):
        return False
    types_ = schema.get("type")
    if isinstance(types_, str):
        types_ = [types_]
    return bool(types_) and "string" in types_


def jsonValue(value):
    """A default value in its JSON form (sets become sorted lists)."""
    if isinstance(value, enum.Enum):
        return jsonValue(value.value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (set, frozenset)):
        return sorted((jsonValue(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [jsonValue(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonValue(v) for k, v in value.items()}
    raise TypeError(f"no JSON form for {value!r}")


# --- descriptions -------------------------------------------------------------------


def _ownDocstring(cls: type) -> str | None:
    """The class's own docstring; not the one ``@dataclass`` makes up from
    the signature, nor one inherited from a base class."""
    doc = cls.__dict__.get("__doc__")
    if not doc or doc.startswith(cls.__name__ + "("):
        return None
    return inspect.cleandoc(doc)


def parseDocstring(doc: str | None) -> tuple[str | None, dict[str, str]]:
    """The summary (the paragraphs before an ``Arguments:`` line) and the
    argument descriptions (``name: text`` lines after it, continued by
    indented lines)."""
    if not doc:
        return None, {}
    lines = doc.splitlines()
    summaryLines: list[str] = []
    arguments: dict[str, str] = {}
    current: str | None = None
    argumentIndent: int | None = None  # indentation of the argument lines
    inArguments = False
    for line in lines:
        stripped = line.strip()
        if not inArguments:
            if stripped.lower() in ("arguments:", "args:"):
                inArguments = True
            else:
                summaryLines.append(line)
            continue
        if not stripped:
            current = None
            continue
        indent = len(line) - len(line.lstrip())
        if argumentIndent is None:
            argumentIndent = indent
        if indent <= argumentIndent:
            name, sep, text = stripped.lstrip("-* ").partition(":")
            name = name.strip().strip("`")
            if sep and name.isidentifier():
                current = name
                arguments[name] = text.strip()
                continue
        if current is not None:
            arguments[current] = (arguments[current] + " " + stripped).strip()
    summary = _clean("\n".join(summaryLines)) or None
    return summary, arguments


def _clean(text: str) -> str:
    paragraphs = [" ".join(p.split()) for p in str(text).strip().split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)


@cache
def bundledDescriptions() -> dict[str, dict[str, dict]]:
    """``descriptions.yaml``: type -> action name -> {description, arguments}."""
    text = (
        resources.files("fontra_workflow_ui")
        .joinpath("descriptions.yaml")
        .read_text(encoding="utf-8")
    )
    data = yaml.safe_load(text) or {}
    return {actionType: data.get(actionType) or {} for actionType in ACTION_TYPES}


# --- packages -------------------------------------------------------------------------


@cache
def _distributionsByModule() -> dict[str, list[str]]:
    return packages_distributions()


def _packageOf(cls: type) -> str | None:
    topLevel = cls.__module__.split(".")[0]
    distributions = _distributionsByModule().get(topLevel)
    if distributions:
        return distributions[0]
    return topLevel


def _distributionVersion(name: str) -> str | None:
    try:
        return version(name)
    except Exception:
        return None
