class CMSError(Exception):
    pass


class CMSValidationError(CMSError):
    pass


class PagePublishError(CMSError):
    pass


class MediaAssetError(CMSError):
    pass


class DuplicateSlugError(CMSError):
    pass


class ContentNotFoundError(CMSError):
    pass
