from pathlib import Path

from tools.repo_checks import find_secrets
from tools.run_pytest import prepare_base_temp


def test_pytest_runner_prepares_temp_parent_in_a_clean_checkout(tmp_path: Path) -> None:
    clean_repository = tmp_path / "clean-repository"

    first = prepare_base_temp(clean_repository)
    second = prepare_base_temp(clean_repository)

    assert first.parent == clean_repository / ".tmp"
    assert first.parent.is_dir()
    assert first != second


def test_secret_scanner_detects_a_token_without_storing_one_in_the_repository(
    tmp_path: Path,
) -> None:
    token = "sk-" + ("a" * 24)
    (tmp_path / "unsafe.txt").write_text(f"token={token}\n", encoding="utf-8")

    assert find_secrets(tmp_path) == ["unsafe.txt:1"]


def test_secret_scanner_ignores_only_explicit_temporary_artifacts(
    tmp_path: Path,
) -> None:
    token = "sk-" + ("b" * 24)
    temporary = tmp_path / ".tmp"
    temporary.mkdir()
    (temporary / "fixture.txt").write_text(f"token={token}\n", encoding="utf-8")
    (tmp_path / "managed.txt").write_text(f"token={token}\n", encoding="utf-8")

    assert find_secrets(tmp_path) == ["managed.txt:1"]
