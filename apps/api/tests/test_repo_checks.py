from pathlib import Path

from tools.repo_checks import find_secrets


def test_secret_scanner_detects_a_token_without_storing_one_in_the_repository(
    tmp_path: Path,
) -> None:
    token = "sk-" + ("a" * 24)
    (tmp_path / "unsafe.txt").write_text(f"token={token}\n", encoding="utf-8")

    assert find_secrets(tmp_path) == ["unsafe.txt:1"]
