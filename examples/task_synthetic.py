"""Replay two complete synthetic task proposals without devices or models."""

import json

from robot_learning.apps.task_demo import create_demo_orchestrator


def main():
    orchestrator = create_demo_orchestrator()
    results = []
    for utterance in (b"pick sample", b"clear table"):
        proposed = orchestrator.propose_audio(utterance)
        orchestrator.approve(proposed["proposal_id"])
        completed = orchestrator.preview()
        results.append({"task_id": completed["task_id"],
                        "candidate_count": completed["candidate_count"],
                        "command_published": completed["command_published"]})
    print(json.dumps({"tasks": results, "final_phase": orchestrator.status()["phase"]}))


if __name__ == "__main__":
    main()
