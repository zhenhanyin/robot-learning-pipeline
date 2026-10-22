"""Allowlisted, approval-gated task orchestration for offline previews."""

from dataclasses import dataclass
from typing import Callable, Mapping, Protocol, Sequence, Tuple

from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.core.ports import RobotAdapter
from robot_learning.workflows.motion import dispatch_commands
from robot_learning.workflows.policy_preview import OfflinePolicyRunner


class TaskError(RuntimeError):
    pass


class SpeechRecognizer(Protocol):
    def transcribe(self, audio: bytes) -> str:
        ...


class VisionPlanner(Protocol):
    def select_task(self, transcript: str, frames: Sequence[CameraFrame]) -> str:
        ...


ObservationProvider = Callable[[], Tuple[ArmState, Sequence[CameraFrame], int]]


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    title: str
    runner: OfflinePolicyRunner

    def __post_init__(self):
        if not self.task_id or not self.title:
            raise ValueError("task ID and title are required")


class TaskOrchestrator:
    def __init__(self, speech: SpeechRecognizer, vision: VisionPlanner,
                 observation: ObservationProvider, tasks: Mapping[str, TaskDefinition],
                 max_observation_age_ns: int = 500_000_000, max_frame_skew_ns: int = 30_000_000):
        if not tasks or any(key != task.task_id for key, task in tasks.items()):
            raise ValueError("task registry must contain matching IDs")
        if type(max_observation_age_ns) is not int or max_observation_age_ns <= 0:
            raise ValueError("max_observation_age_ns must be positive")
        if type(max_frame_skew_ns) is not int or max_frame_skew_ns < 0:
            raise ValueError("max_frame_skew_ns must be non-negative")
        self.speech = speech
        self.vision = vision
        self.observation = observation
        self.tasks = dict(tasks)
        self.max_observation_age_ns = max_observation_age_ns
        self.max_frame_skew_ns = max_frame_skew_ns
        self.phase = "idle"
        self.proposal_id = 0
        self.task_id = None
        self.transcript = None
        self.candidate_count = 0
        self.command_published = False

    def status(self) -> dict:
        return {"phase": self.phase, "proposal_id": self.proposal_id if self.task_id else None,
                "task_id": self.task_id, "transcript": self.transcript,
                "candidate_count": self.candidate_count, "command_published": self.command_published,
                "available_tasks": [{"task_id": task.task_id, "title": task.title}
                                    for task in self.tasks.values()]}

    def stop(self) -> dict:
        self.phase = "stopped"
        for task in self.tasks.values():
            task.runner.emergency_stop()
        return self.status()

    def _observation(self) -> Tuple[ArmState, Sequence[CameraFrame], int]:
        state, frames, now_ns = self.observation()
        frames = tuple(frames)
        if type(now_ns) is not int or not 0 <= now_ns - state.timestamp_ns <= self.max_observation_age_ns:
            raise TaskError("observation is stale or from the future")
        if not frames or len({frame.camera_id for frame in frames}) != len(frames) or any(
                             abs(frame.timestamp_ns - state.timestamp_ns) > self.max_frame_skew_ns
                             or frame.timestamp_ns > now_ns for frame in frames):
            raise TaskError("camera frames are missing, stale or from the future")
        return state, frames, now_ns

    def propose_audio(self, audio: bytes) -> dict:
        if self.phase not in ("idle", "completed"):
            raise TaskError("task is not ready for a new proposal")
        if not isinstance(audio, bytes) or not 0 < len(audio) <= 1_048_576:
            raise ValueError("audio input must be 1 to 1048576 bytes")
        try:
            transcript = self.speech.transcribe(audio)
        except Exception as error:
            self.stop()
            raise TaskError("speech recognition failed") from error
        try:
            return self.propose_text(transcript)
        except ValueError as error:
            self.stop()
            raise TaskError("speech recognition returned an invalid transcript") from error

    def propose_text(self, transcript: str) -> dict:
        if self.phase not in ("idle", "completed"):
            raise TaskError("task is not ready for a new proposal")
        if not isinstance(transcript, str) or not 0 < len(transcript.strip()) <= 200:
            raise ValueError("transcript must contain 1 to 200 characters")
        transcript = transcript.strip()
        if any(ord(character) < 32 for character in transcript):
            raise ValueError("transcript contains control characters")
        try:
            _, frames, _ = self._observation()
            selected = self.vision.select_task(transcript, frames)
            if self.phase == "stopped":
                raise TaskError("task is stopped")
            if selected not in self.tasks:
                raise TaskError("planner selected a task outside the allowlist")
        except Exception as error:
            self.stop()
            raise TaskError("task planning failed") from error
        self.proposal_id += 1
        self.task_id = selected
        self.transcript = transcript
        self.candidate_count = 0
        self.command_published = False
        self.phase = "awaiting_approval"
        return self.status()

    def approve(self, proposal_id: int) -> dict:
        if self.phase != "awaiting_approval" or type(proposal_id) is not int or proposal_id != self.proposal_id:
            raise TaskError("matching pending proposal is required")
        self.phase = "approved"
        return self.status()

    def preview(self) -> dict:
        if self.phase != "approved":
            raise TaskError("approved proposal is required")
        try:
            state, frames, now_ns = self._observation()
            commands = self.tasks[self.task_id].runner.preview(state, frames, now_ns)
        except Exception as error:
            self.stop()
            raise TaskError("task preview failed") from error
        if self.phase == "stopped":
            raise TaskError("task is stopped")
        self.candidate_count = len(commands)
        self.phase = "completed"
        return self.status()

    def execute(self, adapter: RobotAdapter, approved_proposal_id: int) -> dict:
        if self.phase != "approved" or type(approved_proposal_id) is not int or approved_proposal_id != self.proposal_id:
            raise TaskError("matching approved proposal is required")
        try:
            state, frames, now_ns = self._observation()
            runner = self.tasks[self.task_id].runner
            commands = runner.preview(state, frames, now_ns)
            self.candidate_count = len(commands)
            self.phase = "executing"
            for command in commands:
                if self.phase != "executing":
                    raise TaskError("task was stopped during execution")
                fresh_state, _, fresh_now_ns = self._observation()
                dispatch_commands(adapter, fresh_state, (command,), runner.envelope,
                                  fresh_now_ns, enabled=True)
                self.command_published = True
                if self.phase != "executing":
                    raise TaskError("task was stopped during execution")
            self.phase = "completed"
            return self.status()
        except Exception as error:
            self.stop()
            raise TaskError("task execution failed") from error
