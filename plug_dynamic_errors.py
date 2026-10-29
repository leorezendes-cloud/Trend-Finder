"""Expected missing pregame evidence is distinct from invalid stored evidence."""
class Unavailable(ValueError):
    pass


class WeeklyReceiptPending(Unavailable):
    """A complete pregame ATS weekly receipt has not been issued yet."""
