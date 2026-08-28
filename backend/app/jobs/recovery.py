from .service import service


def recover_interrupted_jobs() -> int:
    return service().recover()
