import pytest
import yaml

from fontra_workflow_ui.introspect import buildCatalog
from fontra_workflow_ui.validate import (
    RecipeInvalid,
    RecipePolicy,
    assertValidRecipe,
    validateRecipe,
)


@pytest.fixture(scope="module")
def catalog():
    return buildCatalog()


def check(text, catalog, **kwargs):
    return validateRecipe(yaml.safe_load(text), catalog=catalog, **kwargs)


def messages(result):
    return [str(error) for error in result.errors]


VALID = """
steps:
- input: fontra-read
  source: MutatorSans.fontra
  steps:
  - filter: subset-glyphs
    glyphNames: [A, B, C]
- input: fontra-read
  source: Other.designspace
- filter: rename-axes
  axes:
    weight: {name: Weight, tag: wght}
- filter: instantiate
  location: {width: 0}
- filter: scale
  scaleFactor: 2
- filter: amend-cmap
  cmap:
    U+0041: A
    0x42: B
    U+0043:
- filter: trim-variable-glyphs
  moveDefaultBehavior: empty
- filter: generate-palt-vpal-feature
  languageSystems: [[DFLT, dflt], [hani, JAN]]
- fork:
  steps:
  - filter: drop-features
  - output: fontra-write
    destination: preview.fontra
- fork-merge:
  steps:
  - filter: decompose-composites
- output: fontra-write
  destination: output.fontra
"""


def test_a_valid_recipe_passes(catalog):
    result = check(VALID, catalog)
    assert messages(result) == []
    assert result.ok
    assert ("filter", "scale") in result.actions


def test_assert_valid_recipe(catalog):
    assertValidRecipe(yaml.safe_load(VALID), catalog=catalog)
    with pytest.raises(RecipeInvalid) as info:
        assertValidRecipe({"steps": [{"filter": "nope"}]}, catalog=catalog)
    assert "steps[0] (filter: nope)" in str(info.value)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("{}", ["recipe: no 'steps'"]),
        ("[1, 2]", ["recipe: a recipe is a mapping with 'steps'"]),
        ("steps: {a: 1}", ["steps: 'steps' must be a list of steps"]),
        ("steps: [42]", ["steps[0]: a step must be a mapping"]),
        (
            "steps: [{source: x.fontra}]",
            [
                "steps[0]: no step type: a step starts with one of "
                "input, filter, output, fork, fork-merge"
            ],
        ),
        (
            "steps: [{input: fontra-read, filter: scale, source: x}]",
            ["steps[0]: more than one step type: filter, input"],
        ),
        (
            "steps: [{filter: }]",
            ["steps[0]: 'filter' needs an action name"],
        ),
        (
            "steps: [{filter: subset-glyph}]",
            [
                "steps[0] (filter: subset-glyph): no filter action named "
                "'subset-glyph'; did you mean 'subset-glyphs'?"
            ],
        ),
        (
            "steps: [{filter: fontra-write, destination: x}]",
            [
                "steps[0] (filter: fontra-write): no filter action named "
                "'fontra-write'; it is an output action"
            ],
        ),
        (
            "steps: [{filter: scale, scaleFactor: 2, scalefactor: 3}]",
            [
                "steps[0] (filter: scale), argument 'scalefactor': unknown "
                "argument; did you mean 'scaleFactor'?"
            ],
        ),
        (
            "steps: [{filter: drop-kerning, everything: true}]",
            [
                "steps[0] (filter: drop-kerning), argument 'everything': "
                "unknown argument; drop-kerning takes no arguments"
            ],
        ),
        (
            "steps: [{filter: scale}]",
            [
                "steps[0] (filter: scale), argument 'scaleFactor': required "
                "argument missing"
            ],
        ),
        (
            "steps: [{filter: scale, scaleFactor: double}]",
            [
                "steps[0] (filter: scale), argument 'scaleFactor': expected a "
                "number, got 'double'"
            ],
        ),
        (
            "steps: [{filter: scale, scaleFactor: 2, scaleKerning: 'no'}]",
            [
                "steps[0] (filter: scale), argument 'scaleKerning': expected "
                "true or false, got 'no'"
            ],
        ),
        (
            "steps: [{filter: subset-glyphs, glyphNames: A}]",
            [
                "steps[0] (filter: subset-glyphs), argument 'glyphNames': "
                "expected a list of strings, got 'A'"
            ],
        ),
        (
            "steps: [{filter: subset-glyphs, glyphNames: [A, 3]}]",
            [
                "steps[0] (filter: subset-glyphs), argument 'glyphNames': "
                "item 1: expected a string, got 3"
            ],
        ),
        (
            "steps: [{filter: subset-glyphs, layoutHandling: everything}]",
            [
                "steps[0] (filter: subset-glyphs), argument 'layoutHandling': "
                "expected one of 'subset', 'closure', 'ignore', got 'everything'"
            ],
        ),
        (
            "steps: [{filter: instantiate, location: {wght: bold}}]",
            [
                "steps[0] (filter: instantiate), argument 'location': 'wght': "
                "expected a number, got 'bold'"
            ],
        ),
        (
            "steps: [{filter: generate-palt-vpal-feature, "
            "languageSystems: [[DFLT]]}]",
            [
                "steps[0] (filter: generate-palt-vpal-feature), argument "
                "'languageSystems': item 0: expected a list of 2 items, "
                "got ['DFLT']"
            ],
        ),
        (
            "steps: [{fork: something}]",
            ["steps[0] (fork): 'fork' takes no name: write 'fork:' alone"],
        ),
        (
            "steps: [{fork-merge: , glyphNames: [A]}]",
            ["steps[0] (fork-merge), argument 'glyphNames': takes no arguments"],
        ),
        (
            "steps: [{input: fontra-read, source: a.fontra, "
            "steps: [{filter: scale}]}]",
            [
                "steps[0].steps[0] (filter: scale), argument 'scaleFactor': "
                "required argument missing"
            ],
        ),
    ],
)
def test_invalid_recipes_are_refused_with_the_right_message(text, expected, catalog):
    assert messages(check(text, catalog)) == expected


def test_errors_carry_step_action_and_argument(catalog):
    result = check("steps: [{filter: drop-kerning}, {filter: scale}]", catalog)
    (error,) = result.errors
    assert error.path == "steps[1]"
    assert error.stepType == "filter"
    assert error.action == "scale"
    assert error.argument == "scaleFactor"
    assert error.toJSON()["text"] == str(error)


def test_all_errors_are_reported_at_once(catalog):
    result = check(
        "steps: [{filter: scale}, {filter: nope}, {output: fontra-write}]", catalog
    )
    assert [e.path for e in result.errors] == ["steps[0]", "steps[1]", "steps[2]"]


def test_variables_are_accepted_and_listed(catalog):
    text = """
steps:
- input: fontra-read
  source: "{family}.fontra"
- filter: scale
  scaleFactor: "{factor}"
- filter: instantiate
  location: {wght: "{ weight }"}
- output: fontra-write
  destination: "{family}-{style}.fontra"
"""
    result = check(text, catalog)
    assert result.ok, messages(result)
    assert result.variables == {"family", "factor", "weight", "style"}


def test_an_action_name_may_be_a_variable(catalog):
    text = "steps: [{filter: '{which}', anything: 1}]"
    result = check(text, catalog)
    assert result.ok
    assert result.variables == {"which"}
    assert messages(check(text, catalog, substitutions={"which": "scale"})) == [
        "steps[0] (filter: scale), argument 'anything': unknown argument; "
        "arguments are scaleFactor, scaleFontMetrics, scaleKerning",
        "steps[0] (filter: scale), argument 'scaleFactor': required argument "
        "missing",
    ]


def test_substitutions_are_applied_first(catalog):
    text = "steps: [{filter: scale, scaleFactor: '{factor}'}]"
    assert check(text, catalog, substitutions={"factor": 2}).ok
    bad = check(text, catalog, substitutions={"factor": "big"})
    assert messages(bad) == [
        "steps[0] (filter: scale), argument 'scaleFactor': expected a number, "
        "got 'big'"
    ]
    missing = check(text, catalog, substitutions={})
    assert messages(missing) == ["recipe: no value for the substitution 'factor'"]


def test_empty_option_values_are_accepted(catalog):
    pytest.importorskip("fontra_compile")
    text = """
steps:
- output: compile-fontmake
  destination: out.ttf
  options:
    flatten-components:
    overlaps-backend: pathops
"""
    assert check(text, catalog).ok


# --- policies (what a hosted runner refuses) ------------------------------------

POLICY = RecipePolicy(
    deniedActions=frozenset({"fontra-read", "fontra-write"}),
    denyPathArguments=True,
    reason="no files here",
)


def test_policy_refuses_denied_actions(catalog):
    text = """
steps:
- input: fontra-read
  source: /etc/passwd
- output: fontra-write
  destination: ../../x.fontra
"""
    assert check(text, catalog).ok  # fine locally
    assert messages(check(text, catalog, policy=POLICY)) == [
        "steps[0] (input: fontra-read): this action is not allowed here: no files here",
        "steps[1] (output: fontra-write): this action is not allowed here: "
        "no files here",
    ]


def test_policy_refuses_path_arguments(catalog):
    text = """
steps:
- filter: subset-glyphs
  glyphNamesFile: /etc/passwd
  glyphNames: [A]
- filter: add-features
  featureFile: features.fea
"""
    assert messages(check(text, catalog, policy=POLICY)) == [
        "steps[0] (filter: subset-glyphs), argument 'glyphNamesFile': file and "
        "folder paths are not allowed here: no files here",
        "steps[1] (filter: add-features), argument 'featureFile': file and "
        "folder paths are not allowed here: no files here",
    ]


def test_policy_refuses_nested_steps(catalog):
    text = """
steps:
- fork:
  steps:
  - output: fontra-write
    destination: x.fontra
"""
    assert [e.path for e in check(text, catalog, policy=POLICY).errors] == [
        "steps[0].steps[0]"
    ]


# --- header blocks: inputs, outputs, parameters, assets ---------------------------

HEADED = """
shareable: true
inputs:
  latin: {description: The Latin font}
  cjk:
outputs: [result]
parameters:
  factor: {default: 1.0}
assets:
  features: features/extra.fea
  glyphs: {path: lists/keep.txt}
steps:
- input: fontra-read
  source: "{latin}"
- filter: subset-glyphs
  glyphNamesFile: "{glyphs}"
- filter: add-features
  featureFile: "{features}"
- filter: scale
  scaleFactor: "{factor}"
- output: fontra-write
  destination: "{result}"
"""


def test_header_blocks_declare_slots(catalog):
    result = check(HEADED, catalog)
    assert messages(result) == []
    assert result.slots == {
        "latin": "inputs",
        "cjk": "inputs",
        "result": "outputs",
        "factor": "parameters",
        "features": "assets",
        "glyphs": "assets",
    }
    assert result.shareable
    assert result.variables == {"latin", "glyphs", "features", "factor", "result"}


def test_split_recipe_hands_only_the_engine_part_on():
    from fontra_workflow_ui.validate import engineConfig, splitRecipe

    config = yaml.safe_load(HEADED)
    header, engine = splitRecipe(config)
    assert set(header) == {"shareable", "inputs", "outputs", "parameters", "assets"}
    assert list(engine) == ["steps"]
    assert engineConfig(config) == engine


def test_the_engine_runs_a_recipe_without_its_header(tmp_path, catalog):
    import asyncio

    from fontra.workflow.workflow import Workflow

    from fontra_workflow_ui.validate import engineConfig

    config = yaml.safe_load("""
inputs: {font: }
steps:
- filter: drop-kerning
""")
    assert check(yaml.safe_dump(config), catalog).ok

    async def run():
        async with Workflow(
            config=engineConfig(config), parentDir=tmp_path
        ).endPoints() as endPoints:
            return await endPoints.endPoint.getGlyphMap()

    assert asyncio.run(run()) == {}


def test_undeclared_placeholders_are_refused_when_there_is_a_header(catalog):
    text = """
parameters: [factor]
steps:
- filter: scale
  scaleFactor: "{factr}"
- output: fontra-write
  destination: "{family}-{factor}.fontra"
"""
    assert messages(check(text, catalog)) == [
        "steps[0] (filter: scale), argument 'scaleFactor': placeholder {factr} "
        "is not declared in inputs, outputs, parameters, assets",
        "steps[1] (output: fontra-write), argument 'destination': placeholder "
        "{family} is not declared in inputs, outputs, parameters, assets",
    ]


def test_placeholders_are_flat_names(catalog):
    text = """
parameters: [font]
steps:
- filter: set-font-info
  fontInfo: {familyName: "{font.__class__}", styleName: "a { b"}
"""
    assert messages(check(text, catalog)) == [
        "steps[0] (filter: set-font-info), argument 'fontInfo': placeholder "
        "{font.__class__}: placeholders are flat names (letters, digits, '_' "
        "and '-')",
        "steps[0] (filter: set-font-info), argument 'fontInfo': unbalanced "
        "braces in 'a { b' (write {{ and }} for literal braces)",
    ]


def test_header_mistakes(catalog):
    text = """
inputs: 3
parameters: [a, a b]
outputs: [b]
assets: {b: x.fea, abs: /etc/passwd}
steps: []
"""
    assert messages(check(text, catalog)) == [
        "inputs: expected a mapping of slot names, or a list of names",
        "parameters.a b: a slot name is letters, digits, '_' and '-'",
        "assets.b: slot 'b' is already declared in outputs",
        "assets.abs: assets are paths relative to the recipe, got '/etc/passwd'",
    ]


def test_without_a_header_placeholders_stay_free(catalog):
    assert check("steps: [{filter: scale, scaleFactor: '{f}'}]", catalog).ok


HIVE_LIKE = RecipePolicy(
    deniedActions=frozenset({"fontra-read", "fontra-write"}),
    rejectUnsafePaths=True,
    requireDeclaredPlaceholders=True,
    shareableForbiddenArguments=frozenset({"source"}),
)


def test_policy_requires_declared_placeholders_even_without_header(catalog):
    text = "steps: [{filter: scale, scaleFactor: '{f}'}]"
    assert messages(check(text, catalog, policy=HIVE_LIKE)) == [
        "steps[0] (filter: scale), argument 'scaleFactor': placeholder {f} is "
        "not declared in inputs, outputs, parameters, assets"
    ]


def test_policy_refuses_absolute_and_parent_paths(catalog):
    text = """
assets:
  up: ../secret.fea
  ok: features/ok.fea
steps:
- filter: add-features
  featureFile: /etc/features.fea
- filter: subset-glyphs
  glyphNamesFile: lists/../../x.txt
- filter: add-features
  featureFile: features/ok.fea
- filter: set-font-info
  fontInfo: {copyright: "~/notes"}
"""
    assert check(text, catalog).ok  # fine locally
    assert messages(check(text, catalog, policy=HIVE_LIKE)) == [
        "assets.up: '..' is not allowed here: '../secret.fea'",
        "steps[0] (filter: add-features), argument 'featureFile': absolute "
        "paths and '..' are not allowed here: '/etc/features.fea'",
        "steps[1] (filter: subset-glyphs), argument 'glyphNamesFile': absolute "
        "paths and '..' are not allowed here: 'lists/../../x.txt'",
        "steps[3] (filter: set-font-info), argument 'fontInfo': absolute paths "
        "and '..' are not allowed here: '~/notes'",
    ]


def test_unsafe_paths_through_substitutions(catalog):
    text = """
assets: [fea]
steps:
- filter: add-features
  featureFile: "{fea}"
"""
    assert check(text, catalog, policy=HIVE_LIKE).ok
    result = check(text, catalog, policy=HIVE_LIKE, substitutions={"fea": "/etc/x.fea"})
    assert messages(result) == [
        "steps[0] (filter: add-features), argument 'featureFile': absolute "
        "paths and '..' are not allowed here: '/etc/x.fea'"
    ]


def test_shareable_recipes_cannot_name_literals(catalog):
    policy = RecipePolicy(shareableForbiddenArguments=frozenset({"featureFile"}))
    text = """
shareable: true
inputs:
  fea: {featureFile: shared.fea}
  other: {featureFile: "{fea}"}
steps:
- filter: add-features
  featureFile: features.fea
- filter: add-features
  featureFile: "{fea}"
"""
    assert messages(check(text, catalog, policy=policy)) == [
        "inputs.fea: a shareable recipe cannot name a featureFile literally: "
        "use a placeholder and declare it in inputs",
        "steps[0] (filter: add-features), argument 'featureFile': a shareable "
        "recipe cannot name a featureFile literally: use a placeholder and "
        "declare it in inputs",
    ]
    notShared = text.replace("shareable: true", "shareable: false")
    assert check(notShared, catalog, policy=policy).ok


def test_shareable_recipes_cannot_name_literals_of_a_format(catalog):
    # Every path argument of the catalog has "format": "path": a policy can
    # forbid literals by format, whatever the argument is called.
    policy = RecipePolicy(shareableForbiddenFormats=frozenset({"path"}))
    text = """
shareable: true
assets: [names]
steps:
- filter: subset-glyphs
  glyphNamesFile: keep.txt
  dropGlyphNamesFile: "{names}"
"""
    assert messages(check(text, catalog, policy=policy)) == [
        "steps[0] (filter: subset-glyphs), argument 'glyphNamesFile': a "
        "shareable recipe cannot name a glyphNamesFile literally: use a "
        "placeholder and declare it in inputs"
    ]
