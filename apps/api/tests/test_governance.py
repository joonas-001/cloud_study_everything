from cloud_study_api.config import find_repository_root
from cloud_study_api.governance import validate_repository


def test_repository_skill_packages_are_consistent() -> None:
    packages = validate_repository(find_repository_root())

    assert [(package.package_id, package.version) for package in packages] == [
        ("algorithm", "0.1.0"),
        ("algorithm", "0.2.0"),
        ("algorithm", "0.2.1"),
        ("algorithm", "0.2.2"),
    ]
    assert packages[0].state == "draft"
    assert packages[0].availability == "available"
    assert packages[0].intake == "closed"
    assert (
        packages[0].manifest_sha256
        == "d6b69dc944070d80d5c1bc9f92144ed4bed4c5ef5d650deea8ae649ad21467df"
    )
    assert "intake" not in packages[0].manifest
    assert packages[1].state == "draft"
    assert packages[1].availability == "available"
    assert packages[1].intake == "closed"
    assert "intake" not in packages[1].manifest
    assert packages[2].state == "draft"
    assert packages[2].availability == "available"
    assert packages[2].intake == "closed"
    assert packages[2].manifest["runner_protocol"]["version"] == "1.1.0"
    assert "intake" not in packages[2].manifest
    assert packages[3].state == "draft"
    assert packages[3].availability == "available"
    assert packages[3].intake == "open"
    assert packages[3].manifest["runner_protocol"]["version"] == "1.1.0"
    assert packages[3].manifest_sha256 == (
        "384d1c275dfccbc2eb748c0bbb90e1e25106601ef2d8e711a6ce7538be075336"
    )
    assert "intake" not in packages[3].manifest
