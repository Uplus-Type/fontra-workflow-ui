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
* a :class:`RecipePolicy` can refuse actions, arguments naming files or
  folders, absolute paths and ``..``, undeclared placeholders, and literal
  projects in a shareable recipe (what a hosted runner needs).

Header blocks. A recipe may start with ``inputs:``, ``outputs:``,
``parameters:`` and ``assets:`` blocks (and a ``shareable: true`` flag). The
engine reads only ``steps``; :func:`splitRecipe` separates the header from
what is handed to ``Workflow(...)``. Each block declares *slots*, by name
(a mapping of name -> details, or a list of names). Steps cite slots with
flat placeholders, ``{name}``. Assets are paths relative to the recipe.

Placeholders. A value that is a single ``{name}`` is accepted for any type
(it becomes the substituted value); every name used, whole or inside a
string, is returned as the recipe's variables. When the recipe has a header
(or the policy asks for it), placeholders are strict: each must be a flat
name (``{a.b}`` or ``{a[0]}`` are refused, so are unbalanced braces) naming a
declared slot. A recipe without a header keeps ``fontra-workflow``'s own
rules, so that existing recipes check as before. With
``substitutions`` given, they are applied to the steps first, as
``fontra-workflow`` does, and a missing one is an error.

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
_FLAT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

HEADER_BLOCKS = ("inputs", "outputs", "parameters", "assets")
SHAREABLE_KEY = "shareable"
HEADER_KEYS = HEADER_BLOCKS + (SHAREABLE_KEY,)


@dataclass(frozen=True)
class RecipePolicy:
    """What a runner refuses.

    * ``deniedActions``: action names (any step type);
    * ``denyPathArguments``: any argument naming a file or folder;
    * ``rejectUnsafePaths``: absolute paths and ``..``, in any string of the
      steps and in the assets;
    * ``requireDeclaredPlaceholders``: placeholders that name no slot, even
      in a recipe without a header;
    * ``shareableForbiddenArguments``: in a recipe marked shareable, these
      arguments (and header entries) must be placeholders, not literals.
    """

    deniedActions: frozenset[str] = frozenset()
    denyPathArguments: bool = False
    rejectUnsafePaths: bool = False
    requireDeclaredPlaceholders: bool = False
    shareableForbiddenArguments: frozenset[str] = frozenset()
    reason: str = ""


def splitRecipe(config: Mapping) -> tuple[dict, dict]:
    """(header, engine configuration): the header blocks and the shareable
    flag, and everything else, which is what ``Workflow(config=...)`` gets."""
    header = {k: v for k, v in config.items() if k in HEADER_KEYS}
    engine = {k: v for k, v in config.items() if k not in HEADER_KEYS}
    return header, engine


def engineConfig(config: Mapping) -> dict:
    return splitRecipe(config)[1]


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
    # slot name -> the header block declaring it
    slots: dict[str, str] = field(default_factory=dict)
    shareable: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def toJSON(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [error.toJSON() for error in self.errors],
            "variables": sorted(self.variables),
            "slots": dict(sorted(self.slots.items())),
            "shareable": self.shareable,
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

    if not isinstance(config, Mapping):
        check.errors.append(RecipeError("", "a recipe is a mapping with 'steps'"))
        return check
    header, engine = splitRecipe(config)
    check.shareable = header.get(SHAREABLE_KEY) is True
    _checkHeader(header, policy, check)

    steps = engine.get("steps")
    if steps is None:
        check.errors.append(RecipeError("", "no 'steps'"))
        return check

    strict = any(block in header for block in HEADER_BLOCKS) or bool(
        policy is not None and policy.requireDeclaredPlaceholders
    )
    _checkPlaceholders(steps, "steps", check, strict=strict)
    if check.shareable and policy is not None:
        _checkShareable(steps, "steps", policy, check)

    if substitutions is not None:
        from fontra.workflow.workflow import substituteStrings

        try:
            engine = substituteStrings(engine, dict(substitutions))
        except KeyError as error:
            check.errors.append(
                RecipeError("", f"no value for the substitution {error.args[0]!r}")
            )
            return check
        except (ValueError, IndexError, AttributeError) as error:
            check.errors.append(RecipeError("", f"bad substitution: {error}"))
            return check
        steps = engine.get("steps")

    _checkSteps(steps, "steps", catalog, policy, check)
    return check


# --- header blocks ------------------------------------------------------------------


def _slotNames(block) -> list[str] | None:
    """The slot names a header block declares, or None if it is malformed."""
    if block is None:
        return []
    if isinstance(block, Mapping):
        return [str(name) for name in block]
    if isinstance(block, list):
        names = []
        for item in block:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("name"), str):
                names.append(item["name"])
            elif isinstance(item, Mapping) and len(item) == 1:
                names.append(str(next(iter(item))))
            else:
                return None
        return names
    return None


def _slotEntries(block):
    """(name, details) pairs of a block, details possibly None."""
    if isinstance(block, Mapping):
        return list(block.items())
    entries = []
    for item in block or []:
        if isinstance(item, str):
            entries.append((item, None))
        elif isinstance(item, Mapping) and isinstance(item.get("name"), str):
            entries.append((item["name"], item))
        elif isinstance(item, Mapping) and len(item) == 1:
            entries.append(next(iter(item.items())))
    return entries


def _checkHeader(header: dict, policy, check: RecipeCheck) -> None:
    flag = header.get(SHAREABLE_KEY)
    if flag is not None and not isinstance(flag, bool):
        check.errors.append(RecipeError(SHAREABLE_KEY, "expected true or false"))
    for block in HEADER_BLOCKS:
        if block not in header:
            continue
        names = _slotNames(header[block])
        if names is None:
            check.errors.append(
                RecipeError(
                    block, "expected a mapping of slot names, or a list of names"
                )
            )
            continue
        for name in names:
            if not _FLAT_NAME.match(name):
                check.errors.append(
                    RecipeError(
                        f"{block}.{name}",
                        "a slot name is letters, digits, '_' and '-'",
                    )
                )
            elif name in check.slots:
                check.errors.append(
                    RecipeError(
                        f"{block}.{name}",
                        f"slot '{name}' is already declared in " f"{check.slots[name]}",
                    )
                )
            else:
                check.slots[name] = block
        if block == "assets":
            _checkAssets(header[block], policy, check)
        if check.shareable and policy is not None:
            for name, details in _slotEntries(header[block]):
                for key, value in _literalArguments(
                    details, policy.shareableForbiddenArguments
                ):
                    check.errors.append(
                        RecipeError(
                            f"{block}.{name}",
                            _SHAREABLE_MESSAGE.format(key=key),
                        )
                    )


def _checkAssets(block, policy, check: RecipeCheck) -> None:
    for name, details in _slotEntries(block):
        path = details.get("path") if isinstance(details, Mapping) else details
        if path is None:
            continue
        if not isinstance(path, str):
            check.errors.append(
                RecipeError(f"assets.{name}", "an asset is a path, as a string")
            )
            continue
        if _isAbsolutePath(path):
            check.errors.append(
                RecipeError(
                    f"assets.{name}",
                    f"assets are paths relative to the recipe, got {path!r}",
                )
            )
        elif policy is not None and policy.rejectUnsafePaths and _hasParentPart(path):
            check.errors.append(
                RecipeError(f"assets.{name}", f"'..' is not allowed here: {path!r}")
            )


_SHAREABLE_MESSAGE = (
    "a shareable recipe cannot name a {key} literally: use a placeholder "
    "and declare it in inputs"
)


def _literalArguments(details, names: frozenset[str]):
    if not isinstance(details, Mapping):
        return
    for key, value in details.items():
        if key in names and value is not None and not _isWholePlaceholder(value):
            yield key, value


# --- placeholders, shareable recipes -------------------------------------------------


def _walkSteps(steps, path):
    """(path, step type, action, step) for every step, nested ones too."""
    if not isinstance(steps, list):
        return
    for index, step in enumerate(steps):
        stepPath = f"{path}[{index}]"
        if not isinstance(step, Mapping):
            continue
        stepTypes = [key for key in step if key in STEP_TYPES]
        stepType = stepTypes[0] if len(stepTypes) == 1 else None
        action = step.get(stepType) if stepType else None
        yield stepPath, stepType, action if isinstance(action, str) else None, step
        yield from _walkSteps(step.get("steps"), f"{stepPath}.steps")


def _strings(value):
    """Every string in a value: keys and values of mappings, list items."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _placeholders(text: str) -> list[str] | None:
    """The placeholder fields of a string (raw, as written), or None when it
    is not a valid format string."""
    try:
        return [
            name.strip()
            for _, name, _, _ in string.Formatter().parse(text)
            if name is not None
        ]
    except ValueError:
        return None


def _checkPlaceholders(steps, path, check: RecipeCheck, *, strict: bool) -> None:
    for stepPath, stepType, action, step in _walkSteps(steps, path):
        shownAction = action if not _isWholePlaceholder(action) else None
        for key, value in step.items():
            if key == "steps":
                continue
            argument = None if key == stepType else str(key)
            for text in _strings(value if key == stepType else {key: value}):
                names = _placeholders(text)
                if names is None and not strict:
                    continue  # the engine only formats strings when substituting
                if names is None:
                    check.errors.append(
                        RecipeError(
                            stepPath,
                            f"unbalanced braces in {text!r} (write {{{{ and }}}} "
                            "for literal braces)",
                            stepType,
                            shownAction,
                            argument,
                        )
                    )
                    continue
                for name in names:
                    message = None
                    if not _FLAT_NAME.match(name):
                        if not strict:
                            continue
                        message = (
                            f"placeholder {{{name}}}: placeholders are flat names "
                            "(letters, digits, '_' and '-')"
                        )
                    else:
                        check.variables.add(name)
                        if strict and name not in check.slots:
                            message = (
                                f"placeholder {{{name}}} is not declared in "
                                + ", ".join(HEADER_BLOCKS)
                            )
                    if message:
                        check.errors.append(
                            RecipeError(
                                stepPath, message, stepType, shownAction, argument
                            )
                        )


def _checkShareable(steps, path, policy: RecipePolicy, check: RecipeCheck) -> None:
    for stepPath, stepType, action, step in _walkSteps(steps, path):
        for key, value in _literalArguments(
            {k: v for k, v in step.items() if k not in ("steps", stepType)},
            policy.shareableForbiddenArguments,
        ):
            check.errors.append(
                RecipeError(
                    stepPath,
                    _SHAREABLE_MESSAGE.format(key=key),
                    stepType,
                    action,
                    key,
                )
            )


def _isWholePlaceholder(value) -> bool:
    if not isinstance(value, str):
        return False
    m = _VARIABLE.match(value)
    return m is not None and bool(m.group(1))


# --- paths ---------------------------------------------------------------------------


def _isAbsolutePath(text: str) -> bool:
    return text.startswith(("/", "\\", "~")) or bool(re.match(r"^[A-Za-z]:", text))


def _hasParentPart(text: str) -> bool:
    return ".." in re.split(r"[/\\]", text)


def _unsafePath(text: str) -> bool:
    return _isAbsolutePath(text) or _hasParentPart(text)


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
    if _isWholePlaceholder(actionName):
        # The action itself is a substitution: nothing to check until the
        # recipe is run with a value for it.
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
        if policy is not None and policy.rejectUnsafePaths:
            unsafe = [text for text in _strings(value) if _unsafePath(text)]
            if unsafe:
                error(
                    f"absolute paths and '..' are not allowed here: {unsafe[0]!r}",
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
    if _isWholePlaceholder(value):
        return []  # any type, once substituted

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
