import importlib

def test_frontend_app_has_main():
    module = importlib.import_module("frontend.app")
    assert hasattr(module, "main")
    assert callable(module.main)
