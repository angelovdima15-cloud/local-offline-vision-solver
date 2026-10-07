from pathlib import Path
import json
import numpy as np

from PIL import Image
import pytest

from local_vision_solver.checks import numeric_expression, UnsafeExpression, check_equalities
from local_vision_solver.config import InferenceConfig, load_config
from local_vision_solver.models import Draft, NumericCheck
from local_vision_solver.render import CardRenderer, RenderingError, answer_text
from local_vision_solver.pipeline import validate_reading
from local_vision_solver.models import Reading
from local_vision_solver.locking import inference_lock

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("expression", ["__import__('os').system('whoami')", "open('secret')", "(1).__class__",
    "[x for x in range(100)]", "lambda: 1", "sqrt(-1)", "1/0", "10**100000", "True", "nan"])
def test_model_expressions_cannot_execute_code_or_unbounded_math(expression):
    with pytest.raises(UnsafeExpression):
        numeric_expression(expression)


def test_exact_arithmetic_and_trigonometry():
    assert numeric_expression("0.1 + 0.2") == numeric_expression("0.3")
    assert numeric_expression("sqrt(144)") == 12
    assert numeric_expression("sin(pi/2)") == 1
    values = check_equalities([NumericCheck(label="ok", left="3*12+4", right="40", absolute_tolerance=0),
                              NumericCheck(label="bad", left="3*12+4", right="41", absolute_tolerance=0)])
    assert [v["passed"] for v in values] == [True, False]


@pytest.mark.parametrize("endpoint", ["https://api.openai.com", "http://192.168.1.2:8080",
                                     "http://127.0.0.1.evil.example", "http://user@127.0.0.1:8081",
                                     "http://localhost:8081", "http://127.0.0.1:8081/path"])
def test_inference_rejects_remote_or_ambiguous_endpoints(endpoint):
    with pytest.raises(ValueError):
        InferenceConfig(endpoint=endpoint)


def test_math_has_transparent_background_and_visible_glyphs(tmp_path):
    config = load_config(ROOT / "config.toml").render
    renderer = CardRenderer(config, tmp_path)
    equation = renderer.math_image(r"x = \frac{36}{3} = 12")
    alpha = equation.getchannel("A")
    assert alpha.getextrema() == (0, 255)
    assert equation.width < config.width - 2*config.margin
    draft = Draft.model_validate_json((ROOT / "examples" / "answer_math.json").read_text(encoding="utf-8"))
    manifest = renderer.render(draft, tmp_path / "cards")
    assert len(manifest) == 2
    with Image.open(tmp_path / "cards" / "answer_01.png") as image:
        # Formula region must contain BOTH black background and white math, not a white rectangle.
        colors = {tuple(pixel) for pixel in np.asarray(image.crop((28, 104, 350, 160))).reshape(-1, 3)}
        assert (0, 0, 0) in colors and (255, 255, 255) in colors


def test_long_kazakh_text_is_paginated_without_character_loss(tmp_path):
    config = load_config(ROOT / "config.toml").render
    renderer = CardRenderer(config, tmp_path)
    draft = Draft.model_validate_json((ROOT / "examples" / "answer_kazakh.json").read_text(encoding="utf-8"))
    source = draft.solution[0].content
    for paragraph in source.split("\n"):
        assert "".join(renderer.wrap(paragraph, renderer.font)) == paragraph
    cards = renderer.render(draft, tmp_path / "kazakh")
    assert len(cards) > 1
    assert "Ғ" in answer_text(draft) and "І" in answer_text(draft)
    assert cards[0]["section"] == ""  # Essay starts immediately, no fabricated final answer.
    for card in cards:
        with Image.open(tmp_path / "kazakh" / card["file"]) as image:
            assert image.size == (832, 992)


def test_wide_formula_is_rejected_instead_of_becoming_tiny(tmp_path):
    renderer = CardRenderer(load_config(ROOT / "config.toml").render, tmp_path)
    with pytest.raises(RenderingError, match="too large"):
        renderer.math_image(" + ".join(["x^{123}"] * 40))


def test_unsupported_latex_does_not_silently_disappear(tmp_path):
    renderer = CardRenderer(load_config(ROOT / "config.toml").render, tmp_path)
    with pytest.raises(RenderingError, match="Unsupported formula"):
        renderer.math_image(r"\begin{align}x&=12\end{align}")


def test_inference_lock_prevents_two_active_sessions(tmp_path):
    with inference_lock(tmp_path):
        with pytest.raises(RuntimeError, match="Another session"):
            with inference_lock(tmp_path):
                pytest.fail("Second session entered")
    with inference_lock(tmp_path):
        pass  # Lock is released by OS, not dependent on removing a stale directory.
