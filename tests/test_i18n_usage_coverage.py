import ast
from pathlib import Path

from app_core.language import LANGUAGES


PROJECT_I18N_DIRS = ("app_core", "notifications")
DYNAMIC_I18N_KEYS = {"uptime_day_one", "uptime_day_few", "uptime_day_many"}
DIRECT_LOOKUP_KEYS = {"language_name"}


def _iter_python_files():
    for folder in PROJECT_I18N_DIRS:
        yield from Path(folder).glob("*.py")


def _literal_tr_keys() -> set[str]:
    keys: set[str] = set()
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "tr" or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keys.add(arg.value)
    return keys


def test_all_tr_literal_keys_exist_in_dictionary():
    known_keys = set(LANGUAGES["en"].keys())
    unknown = sorted(_literal_tr_keys() - known_keys)
    assert not unknown, f"Unknown translation keys used via tr(...): {unknown}"


def test_all_dictionary_keys_are_used_somewhere():
    known_keys = set(LANGUAGES["en"].keys())
    used = _literal_tr_keys() | DYNAMIC_I18N_KEYS | DIRECT_LOOKUP_KEYS
    unused = sorted(known_keys - used)
    assert not unused, f"Unused translation keys in dictionary: {unused}"
