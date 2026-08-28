"""Plan independent mock-test timing and outcomes without touching Tk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from work_transfer_app.config import MockTestDefinition


class RandomSource(Protocol):
    """Provide the two random operations used by mock-test planning."""

    def randint(self, lower: int, upper: int) -> int:
        """Return an integer inside the inclusive bounds."""

        ...

    def random(self) -> float:
        """Return a floating-point value in the half-open unit interval."""

        ...


@dataclass(frozen=True, slots=True)
class MockTestPlan:
    """Describe one scheduled mock test and its predetermined outcome."""

    test: MockTestDefinition
    delay_ms: int
    is_pass: bool


def plan_mock_tests(
    definitions: tuple[MockTestDefinition, ...],
    random_source: RandomSource,
) -> tuple[MockTestPlan, ...]:
    """Plan 1-5 second completions with an independent ten-percent fail rate."""

    return tuple(
        MockTestPlan(
            test=definition,
            delay_ms=random_source.randint(1000, 5000),
            is_pass=random_source.random() >= 0.10,
        )
        for definition in definitions
    )
