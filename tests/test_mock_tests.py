"""Behavior tests for deterministic mock-test run planning."""

from work_transfer_app.config import MockTestDefinition
from work_transfer_app.ui.mock_tests import plan_mock_tests


class SequenceRandom:
    """Return controlled timing and outcome values without real randomness."""

    def __init__(self) -> None:
        """Prepare inclusive timing bounds and the failure-rate boundary."""

        self._delays = iter((1000, 5000))
        self._outcomes = iter((0.099, 0.10))

    def randint(self, lower: int, upper: int) -> int:
        """Return a planned delay while asserting the configured bounds."""

        assert (lower, upper) == (1000, 5000)
        return next(self._delays)

    def random(self) -> float:
        """Return one value below and one value at the pass boundary."""

        return next(self._outcomes)


def test_mock_test_plans_use_inclusive_delays_and_ten_percent_failure() -> None:
    """Plan independent test completion times with an exact ten-percent cutoff."""

    definitions = (
        MockTestDefinition("first", "First test"),
        MockTestDefinition("second", "Second test"),
    )

    plans = plan_mock_tests(definitions, SequenceRandom())

    assert [(plan.test.id, plan.delay_ms, plan.is_pass) for plan in plans] == [
        ("first", 1000, False),
        ("second", 5000, True),
    ]
