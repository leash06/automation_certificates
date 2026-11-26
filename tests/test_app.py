from streamlit.testing.v1 import AppTest


def test_app_starts_without_errors():
    # Smoke test: the first screen loads and asks for a template.
    # The path is relative to this test file, so go up one folder to app.py.
    app = AppTest.from_file("../app.py").run(timeout=30)
    assert not app.exception
    assert app.title[0].value == "Certificate Generator"
    assert app.error == []
