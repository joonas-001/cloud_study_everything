from cloud_study_api.config import find_repository_root
from cloud_study_api.governance import validate_repository


def test_repository_skill_packages_are_consistent() -> None:
    packages = validate_repository(find_repository_root())

    assert [(package.package_id, package.version) for package in packages] == [
        ("algorithm", "0.1.0")
    ]
    assert packages[0].state == "draft"
    assert packages[0].availability == "available"
