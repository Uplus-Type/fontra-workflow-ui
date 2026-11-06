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
