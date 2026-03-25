class LeadsError(Exception):
    pass


class LeadNotFoundError(LeadsError):
    pass


class InvalidStatusTransitionError(LeadsError):
    pass
