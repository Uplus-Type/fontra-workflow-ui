"""Check a ``fontra-workflow`` recipe against the action catalog, without
running it.

Every problem is reported with where it is: the step (``steps[2].steps[0]``),
its step type and action, and the argument. Checks:

* the recipe has a ``steps`` list, each step is a mapping with exactly one
  step type (``input``, ``filter``, ``output``, ``fork``, ``fork-merge``);
* the action exists for that step type (with a suggestion when it is close
  to another name, or exists under another step type);
* ``fork`` and ``fork-merge`` take neither a name nor arguments;
* arguments: none unknown, none required missing, each of the type its
  action declares;
* a :class:`RecipePolicy` can refuse actions, and arguments naming files or
  folders (a hosted runner must not let a recipe read or write the server's
  files).

Substitutions (``{family}``): with ``substitutions`` given, they are applied
first, as ``fontra-workflow`` does, and a missing one is an error. Without,
a value that is a single ``{name}`` is accepted for any type (it becomes the
substituted value), and every name used, whole or inside a string, is
returned as the recipe's variables.

One leniency: inside a mapping argument, an empty value (YAML ``key:`` with
nothing after it) is accepted whatever the declared type, because recipes use
it for options without a value (``options: {flatten-components: }``).
"""

from __future__ import annotations

import difflib
import re
import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .introspect import (
    ACTION_TYPES,
    STEP_TYPES,
    STRUCTURAL_STEP_TYPES,
    ActionInfo,
    Catalog,
    buildCatalog,
)

_VARIABLE = re.compile(r"^{\s*([^{}]*?)\s*}$")


@dataclass(frozen=True)
class RecipePolicy:
    """What a runner refuses. ``deniedActions``: action names (any step
    type); ``denyPathArguments``: refuse arguments naming a file or folder."""

    deniedActions: frozenset[str] = frozenset()
    denyPathArguments: bool = False
    reason: str = ""


@dataclass(frozen=True)
class RecipeError:
    path: str  # "steps[1].steps[0]", or "" for the recipe itself
    message: str
    stepType: str | None = None
    action: str | None = None
    argument: str | None = None

    def __str__(self) -> str:
        where = self.path or "recipe"
        if self.stepType in STRUCTURAL_STEP_TYPES:
            where += f" ({self.stepType})"
        elif self.stepType and self.action:
            where += f" ({self.stepType}: {self.action})"
        if self.argument:
            where += f", argument '{self.argument}'"
        return f"{where}: {self.message}"

    def toJSON(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "stepType": self.stepType,
            "action": self.action,
            "argument": self.argument,
            "message": self.message,
            "text": str(self),
        }


@dataclass
class RecipeCheck:
    errors: list[RecipeError] = field(default_factory=list)
    variables: set[str] = field(default_factory=set)
    # (step type, action name) of every step, in recipe order
    actions: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def toJSON(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [error.toJSON() for error in self.errors],
            "variables": sorted(self.variables),
        }


class RecipeInvalid(Exception):
    def __init__(self, check: RecipeCheck):
        self.check = check
        super().__init__("\n".join(str(e) for e in check.errors))


def validateRecipe(
    config: Any,
    *,
    catalog: Catalog | None = None,
    policy: RecipePolicy | None = None,
    substitutions: Mapping[str, Any] | None = None,
) -> RecipeCheck:
    """Check ``config`` (the parsed YAML of a recipe)."""
    if catalog is None:
        catalog = buildCatalog()
    check = RecipeCheck()

    if substitutions is not None:
        from fontra.workflow.workflow import substituteStrings

        try:
            config = substituteStrings(config, dict(substitutions))
        except KeyError as error:
            check.errors.append(
                RecipeError("", f"no value for the substitution {error.args[0]!r}")
            )
            return check
        except (ValueError, IndexError) as error:
            check.errors.append(RecipeError("", f"bad substitution: {error}"))
            return check

    if not isinstance(config, Mapping):
        check.errors.append(RecipeError("", "a recipe is a mapping with 'steps'"))
        return check
    steps = config.get("steps")
    if steps is None:
        check.errors.append(RecipeError("", "no 'steps'"))
        return check
    _checkSteps(steps, "steps", catalog, policy, check)
    return check


def assertValidRecipe(config, **kwargs) -> RecipeCheck:
    check = validateRecipe(config, **kwargs)
    if not check.ok:
        raise RecipeInvalid(check)
    return check


def _checkSteps(steps, path, catalog, policy, check) -> None:
    if not isinstance(steps, list):
        check.errors.append(RecipeError(path, "'steps' must be a list of steps"))
        return
    for index, step in enumerate(steps):
        _checkStep(step, f"{path}[{index}]", catalog, policy, check)


def _checkStep(step, path, catalog: Catalog, policy, check: RecipeCheck) -> None:
    if not isinstance(step, Mapping):
        check.errors.append(RecipeError(path, "a step must be a mapping"))
        return
    stepTypes = [key for key in step if key in STEP_TYPES]
    if not stepTypes:
        check.errors.append(
            RecipeError(
                path,
                "no step type: a step starts with one of " + ", ".join(STEP_TYPES),
            )
        )
        return
    if len(stepTypes) > 1:
        check.errors.append(
            RecipeError(
                path, "more than one step type: " + ", ".join(sorted(stepTypes))
            )
        )
        return

    stepType = stepTypes[0]
    actionName = step[stepType]
    arguments = {k: v for k, v in step.items() if k not in (stepType, "steps")}
    if "steps" in step:
        _checkSteps(step["steps"], f"{path}.steps", catalog, policy, check)

    if stepType in STRUCTURAL_STEP_TYPES:
        if actionName not in (None, ""):
            check.errors.append(
                RecipeError(
                    path,
                    f"'{stepType}' takes no name: write '{stepType}:' alone",
                    stepType,
                )
            )
        for name in arguments:
            check.errors.append(
                RecipeError(path, "takes no arguments", stepType, argument=name)
            )
        return

    if not isinstance(actionName, str) or not actionName:
        check.errors.append(
            RecipeError(path, f"'{stepType}' needs an action name", stepType)
        )
        return
    variable = _VARIABLE.match(actionName)
    if variable is not None and variable.group(1):
        # The action itself is a substitution: nothing to check until the
        # recipe is run with a value for it.
        check.variables.add(variable.group(1))
        return
    check.actions.append((stepType, actionName))

    info = catalog.get(stepType, actionName)
    if info is None:
        check.errors.append(
            RecipeError(
                path,
                _unknownActionMessage(stepType, actionName, catalog),
                stepType,
                actionName,
            )
        )
        return

    if policy is not None and actionName in policy.deniedActions:
        check.errors.append(
            RecipeError(
                path,
                "this action is not allowed here"
                + (f": {policy.reason}" if policy.reason else ""),
                stepType,
                actionName,
            )
        )
        return

    _checkArguments(info, arguments, path, policy, check)


def _unknownActionMessage(stepType: str, actionName: str, catalog: Catalog) -> str:
    for otherType in ACTION_TYPES:
        if otherType != stepType and catalog.get(otherType, actionName) is not None:
            return (
                f"no {stepType} action named '{actionName}'; "
                f"it is a{'n' if otherType[0] in 'aeiou' else ''} {otherType} action"
            )
    message = f"no {stepType} action named '{actionName}'"
    close = difflib.get_close_matches(
        actionName, list(catalog.actions.get(stepType, {})), n=1
    )
    if close:
        message += f"; did you mean '{close[0]}'?"
    return message


def _checkArguments(
    info: ActionInfo, arguments: dict, path: str, policy, check: RecipeCheck
) -> None:
    def error(message, argument=None):
        check.errors.append(
            RecipeError(path, message, info.actionType, info.name, argument)
        )

    properties = info.properties
    for name, value in arguments.items():
        schema = properties.get(name)
        if schema is None:
            message = "unknown argument"
            close = difflib.get_close_matches(str(name), list(properties), n=1)
            if close:
                message += f"; did you mean '{close[0]}'?"
            elif properties:
                message += "; arguments are " + ", ".join(properties)
            else:
                message += f"; {info.name} takes no arguments"
            error(message, str(name))
            continue
        if (
            policy is not None
            and policy.denyPathArguments
            and info.isPathArgument(name)
        ):
            error(
                "file and folder paths are not allowed here"
                + (f": {policy.reason}" if policy.reason else ""),
                name,
            )
            continue
        for problem in _checkValue(value, schema, check.variables):
            error(problem, name)

    for name in info.required:
        if name not in arguments:
            error("required argument missing", name)


# --- values against the generated schemas ---------------------------------------


def _checkValue(value, schema: dict, variables: set) -> list[str]:
    """Problems of ``value`` against ``schema`` (the subset of JSON schema
    :mod:`fontra_workflow_ui.introspect` generates)."""
    if isinstance(value, str):
        variables.update(_variablesIn(value))
        m = _VARIABLE.match(value)
        if m is not None and m.group(1):
            return []  # a whole-value variable: any type, once substituted

    if "anyOf" in schema:
        for member in schema["anyOf"]:
            if not _checkValue(value, member, set()):
                _checkValue(value, member, variables)  # collect its variables
                return []
        return [f"expected {describeSchema(schema)}, got {_show(value)}"]

    if "enum" in schema and value not in schema["enum"]:
        choices = ", ".join(_show(v) for v in schema["enum"])
        return [f"expected one of {choices}, got {_show(value)}"]

    expected = schema.get("type")
    if expected is None:
        return []
    expectedTypes = [expected] if isinstance(expected, str) else list(expected)
    actualType = _jsonType(value)
    if actualType not in expectedTypes and not (
        actualType == "integer" and "number" in expectedTypes
    ):
        return [f"expected {describeSchema(schema)}, got {_show(value)}"]

    problems: list[str] = []
    if actualType == "array":
        prefix = schema.get("prefixItems")
        if prefix is not None:
            if not (
                schema.get("minItems", 0)
                <= len(value)
                <= schema.get("maxItems", len(value))
            ):
                return [f"expected {describeSchema(schema)}, got {_show(value)}"]
            for index, (item, itemSchema) in enumerate(zip(value, prefix)):
                problems += [
                    f"item {index}: {p}"
                    for p in _checkValue(item, itemSchema, variables)
                ]
        elif "items" in schema:
            for index, item in enumerate(value):
                problems += [
                    f"item {index}: {p}"
                    for p in _checkValue(item, schema["items"], variables)
                ]
    elif actualType == "object":
        keySchema = schema.get("propertyNames")
        valueSchema = schema.get("additionalProperties")
        for key, item in value.items():
            if keySchema is not None:
                problems += [
                    f"key {_show(key)}: {p}"
                    for p in _checkValue(key, keySchema, variables)
                ]
            if isinstance(valueSchema, dict) and item is not None:
                problems += [
                    f"{_show(key)}: {p}"
                    for p in _checkValue(item, valueSchema, variables)
                ]
    return problems


def _variablesIn(text: str) -> set[str]:
    """The substitution names in a string (``str.format`` fields)."""
    try:
        fields = string.Formatter().parse(text)
        return {name.strip() for _, name, _, _ in fields if name and name.strip()}
    except ValueError:
        return set()


def _jsonType(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


_TYPE_WORDS = {
    "string": "a string",
    "integer": "an integer",
    "number": "a number",
    "boolean": "true or false",
    "null": "nothing",
    "array": "a list",
    "object": "a mapping",
}


def describeSchema(schema: dict) -> str:
    if "anyOf" in schema:
        return " or ".join(describeSchema(member) for member in schema["anyOf"])
    if "enum" in schema:
        return "one of " + ", ".join(_show(v) for v in schema["enum"])
    expected = schema.get("type")
    if expected is None:
        return "anything"
    if isinstance(expected, list):
        return " or ".join(_TYPE_WORDS.get(t, t) for t in expected)
    if expected == "array" and "prefixItems" in schema:
        return f"a list of {len(schema['prefixItems'])} items"
    if expected == "array" and "items" in schema:
        return f"a list of {_plural(schema['items'])}"
    if expected == "object" and isinstance(schema.get("additionalProperties"), dict):
        inner = schema["additionalProperties"]
        if inner.get("type"):
            return f"a mapping of {_plural(inner)}"
    return _TYPE_WORDS.get(expected, expected)


def _plural(schema: dict) -> str:
    words = {
        "string": "strings",
        "integer": "integers",
        "number": "numbers",
        "boolean": "booleans",
        "array": "lists",
        "object": "mappings",
    }
    expected = schema.get("type")
    if isinstance(expected, str) and expected in words:
        return words[expected]
    return "values"


def _show(value) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."
