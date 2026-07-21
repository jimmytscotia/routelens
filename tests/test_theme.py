from routelens.app import create_app


def _client(tmp_path):
    return create_app({"DATABASE": str(tmp_path / "theme.db"), "TESTING": True}).test_client()


def test_theme_toggle_control_present(tmp_path):
    body = _client(tmp_path).get("/").data.decode()

    assert 'class="themetoggle"' in body
    for pref in ("auto", "dark", "light"):
        assert f'data-theme-set="{pref}"' in body


def test_no_flash_script_sets_theme_before_paint(tmp_path):
    body = _client(tmp_path).get("/").data.decode()

    # The inline head script reads the stored preference and sets data-theme
    # before the body paints (no flash of the wrong theme).
    head = body.split("<title>", 1)[0]
    assert "rl-theme" in head
    assert "data-theme" in head
    assert "prefers-color-scheme" in head


def test_light_theme_tokens_defined(tmp_path):
    body = _client(tmp_path).get("/").data.decode()

    assert ':root[data-theme="light"]' in body
    # Dark remains the default token set.
    assert "color-scheme:dark" in body
