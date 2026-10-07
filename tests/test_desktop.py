from pathlib import Path
from local_vision_solver.app_paths import AppPaths
from local_vision_solver.config import product_config,save_config,load_config


def test_product_paths_independent_of_cwd(tmp_path,monkeypatch):
    paths=AppPaths.for_user(tmp_path/'данные с пробелами').ensure()
    save_config(product_config(paths),paths.config)
    monkeypatch.chdir(tmp_path)
    config=load_config(paths.config,paths.data)
    assert config.pipeline.session_directory==paths.sessions
    assert config.runtime.model.parent==paths.models
    assert config.runtime.executable.parent==paths.runtime
    assert config.render.math_engine=='mathtext'


def test_invalid_render_config_fails_before_runtime():
    import pytest
    from local_vision_solver.config import RenderConfig
    with pytest.raises(ValueError):RenderConfig(font_size=20,minimum_math_font_size=34)
    with pytest.raises(ValueError):RenderConfig(height=240,margin=100)
