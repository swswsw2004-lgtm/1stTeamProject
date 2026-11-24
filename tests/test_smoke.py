"""pytest 실행 환경 확인용 기본 테스트 (역할1)"""


def test_core_package_importable():
    import core  # noqa: F401  core 폴더를 import 할 수 있어야 함
