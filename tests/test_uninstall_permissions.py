from pathlib import Path


def test_uninstall_handles_permission_denied_without_failing():
    code = Path('uninstall-symo.sh').read_text(encoding='utf-8')
    assert 'set -u -o pipefail' in code
    assert 'sudo -n rm -rf "$target"' in code
    assert 'Warning: unable to remove $target (insufficient permissions)' in code


def test_uninstall_covers_package_install_paths():
    code = Path('uninstall-symo.sh').read_text(encoding='utf-8')
    assert '"/usr/bin/symo"' in code
    assert '"/opt/symo"' in code
