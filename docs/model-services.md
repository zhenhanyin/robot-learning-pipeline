# Model and service integrations

v0.7.0 adds explicit adapters around external model providers. The package does not install a speech/VLM/VLA provider, load a checkpoint by itself, or ship model weights. Integrations are opt-in and use Python protocols or JSON over HTTPS; no pickle or executable model artifact is accepted by the service clients.

## Policy manifest

Start with `configs/policies/act-http.example.json` and set only user-owned endpoints and camera/joint mappings. Check its schema without importing the backend or contacting a service:

```bash
robot-learning validate-policy-manifest configs/policies/act-http.example.json
robot-learning validate-policy-manifest configs/policies/act-http.example.json \
  --training-plan configs/training/act-example.json
```

`joint_names`, units, `camera_map`, gripper action membership, image encoding, and action width must match the dataset and checkpoint. A configured affine transform uses `(value - offset) / scale` for observations and the inverse operation for predicted actions; supply values exported from the **same** checkpoint. The example omits normalization because none is assumed.

For a local model loader, set `checkpoint_env` to an environment variable name. The process resolves that variable to a local file or directory at runtime and passes it as `checkpoint_path` to the configured `module:factory`. The manifest stores neither the model path nor weights. A remote backend instead receives its endpoint and `api_key_env`; put the credential value in the environment, never in JSON or a URL query string.

The built-in HTTP policy transport sends JSON with a `model`, an `observation`, explicit image encoding/dimensions, and base64 image bytes. It expects an `actions` list of finite vectors. ACT, H-RDT, and OpenPI-shaped responses are still checked by `ModelPolicyClient` for exact joint/gripper width and chunk length before they reach the safety preview.

## Speech and vision APIs

`SpeechToTextHttpClient` sends `audio_base64` and `content_type`; the response must contain a non-empty `text` of at most 200 characters. `VisionTaskHttpClient` sends the transcript, the configured `allowed_tasks`, and up to eight RGB frames. Depth frames are excluded rather than mislabeled. The service must return one `task_id` from the provided allowlist; anything else is rejected before task approval.

Example injection into the existing orchestrator:

```python
from robot_learning.integrations import SpeechToTextHttpClient, VisionTaskHttpClient

speech = SpeechToTextHttpClient(
    "https://speech.example/transcribe", api_key_env="ROBOT_SPEECH_API_KEY"
)
vision = VisionTaskHttpClient(
    "https://vision.example/select-task", allowed_tasks=("pick", "place"),
    api_key_env="ROBOT_VISION_API_KEY",
)
```

Service URLs must use HTTPS; plain HTTP is accepted only for explicit loopback hosts such as `127.0.0.1` or `localhost`. Requests use bounded timeouts, response sizes and payloads. The external provider's data-retention policy remains the user's responsibility. All clients accept an injected transport for offline tests.

## Training plan

`configs/training/act-example.json` is a framework-neutral handoff document, not a trainer. Validate its fields with:

```bash
robot-learning validate-training-plan configs/training/act-example.json
robot-learning validate-training-plan configs/training/act-example.json --check-paths
```

The backend reference points to a user-installed trainer. HDF5/LeRobot plans require a declared action source and explicit joint/action units; VLM ShareGPT plans are reserved for `llama_factory`. Path checking resolves paths relative to the plan file and prevents the output directory from overlapping the input dataset.

Passing `--training-plan` to `validate-policy-manifest` also checks the model family and declared joint/action units match between training and inference configuration.

The service, checkpoint, external training backend, normalization provenance and real model outputs were not available for this offline release. The test suite uses fake backends/transports and does not demonstrate successful training or deployment on a robot.
