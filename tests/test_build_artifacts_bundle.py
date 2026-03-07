from pathlib import Path


def test_build_script_collects_artifacts_into_single_folder():
    code = Path('build.sh').read_text(encoding='utf-8')
    assert 'OUTPUT_DIR="${APP_NAME}-bundle"' in code
    assert 'move_if_exists "app.build"' in code
    assert 'move_if_exists "app.dist"' in code
    assert 'move_if_exists "app.onefile-build"' in code
    assert 'move_if_exists "build_standalone"' in code
    assert 'move_if_exists "${APP_NAME}-standalone"' in code
    assert 'move_if_exists "${APP_NAME}-onefile"' in code
    assert 'move_if_exists "${APP_NAME}-launch"' in code
    assert 'move_if_exists "${APP_NAME}-run"' in code


def test_uninstall_script_removes_all_build_outputs():
    code = Path('uninstall-symo.sh').read_text(encoding='utf-8')
    assert 'SyMo-bundle' in code
    assert 'app.onefile-build' in code
    assert 'build_standalone' in code
    assert 'SyMo-standalone' in code
    assert 'SyMo-launch' in code
    assert 'SyMo-run' in code
    assert '.config/autostart/SyMo.desktop' in code
