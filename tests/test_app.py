from streamlit.testing.v1 import AppTest


def test_app_starts_on_the_design_screen():
    # Smoke test: the first screen loads without errors and asks for a template.
    # The path is relative to this test file, so go up one folder to app.py.
    app = AppTest.from_file("../app.py").run(timeout=30)
    assert not app.exception
    assert app.error == []
    assert any("Create your certificate" in block.value for block in app.markdown)
    # Only the first step is available before a template is uploaded.
    assert app.button(key="nav_design").disabled is False
    assert app.button(key="nav_recipients").disabled is True
