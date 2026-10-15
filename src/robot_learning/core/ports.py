"""Interfaces implemented by robot-specific code and storage backends."""

from typing import Protocol, Sequence

from robot_learning.core.models import ArmAction, ArmState, CameraFrame, RobotCommand


class RobotAdapter(Protocol):
    def read_state(self) -> ArmState:
        ...

    def send_command(self, command: RobotCommand) -> None:
        ...


class CameraAdapter(Protocol):
    def read_frame(self) -> CameraFrame:
        ...


class PolicyClient(Protocol):
    def predict(self, state: ArmState, frames: Sequence[CameraFrame]) -> Sequence[RobotCommand]:
        ...


class EpisodeWriter(Protocol):
    def append_state(self, state: ArmState) -> None:
        ...

    def append_action(self, action: ArmAction) -> None:
        ...

    def append_frame(self, frame: CameraFrame) -> None:
        ...

    def close(self) -> None:
        ...
