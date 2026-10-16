"""Preview one synthetic policy chunk without connecting to a robot."""

import argparse
import json

from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.policies import ModelPolicyClient, PolicySpec
from robot_learning.workflows.policy_preview import OfflinePolicyRunner, SafetyEnvelope


class FakeModel:
    def get_chunk(self, observation):
        return [[0.1], [0.2]]

    def predict_action(self, observation):
        return [[0.1], [0.2]]

    def infer(self, observation):
        return {"actions": [[0.1], [0.2]]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("act", "hrdt", "pi0", "pi0.5"), required=True)
    args = parser.parse_args()
    spec = PolicySpec(args.model, {"head": "base"}, 1, prompt="synthetic pick" if args.model.startswith("pi") else None)
    policy = ModelPolicyClient(spec, FakeModel(), lambda frame: frame.payload)
    envelope = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 1_000_000, 1_000_000, 1_000_000_000)
    runner = OfflinePolicyRunner(policy, envelope)
    state = ArmState("left", 100, (0.0,))
    frame = CameraFrame("base", 100, "raw8", 1, 1, b"\x00")
    commands = runner.preview(state, (frame,), 100)
    print(json.dumps({"model": args.model, "candidate_count": len(commands),
                      "first_joint_targets": commands[0].joint_targets, "command_published": False}))


if __name__ == "__main__":
    main()
