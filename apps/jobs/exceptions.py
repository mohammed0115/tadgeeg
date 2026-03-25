class JobsError(Exception):
    pass


class JobNotFoundError(JobsError):
    pass


class ApplicationAlreadyExistsError(JobsError):
    pass


class JobClosedError(JobsError):
    pass
