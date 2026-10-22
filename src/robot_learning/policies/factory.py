"""Load user-installed policy backends without vendoring model frameworks."""

import importlib
from typing import Mapping

from robot_learning.formats.images import rgb_array
from robot_learning.policies.client import ModelPolicyClient, PolicySpec


def load_component(reference: str, options: Mapping[str, object] = None) -> object:
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise ValueError("component reference must be module:factory")
    module_name, factory_name = reference.split(":")
    if not module_name or not factory_name or any(not part.isidentifier() for part in module_name.split(".")) or not factory_name.isidentifier():
        raise ValueError("invalid component reference")
    if options is not None and not isinstance(options, Mapping):
        raise ValueError("component options must be a mapping")
    factory = getattr(importlib.import_module(module_name), factory_name)
    if not callable(factory):
        raise ValueError("component factory is not callable")
    return factory(**dict(options or {}))


def load_policy(spec: PolicySpec, backend_reference: str,
                backend_options: Mapping[str, object] = None,
                image_format: str = "rgb-array") -> ModelPolicyClient:
    if image_format == "rgb-array":
        encoder = rgb_array
    elif image_format == "bytes":
        encoder = lambda frame: frame.payload
    else:
        raise ValueError("image_format must be rgb-array or bytes")
    backend = load_component(backend_reference, backend_options)
    method = "get_chunk" if spec.model == "act" else "predict_action" if spec.model == "hrdt" else "infer"
    if not callable(getattr(backend, method, None)):
        raise ValueError("backend does not implement " + method)
    return ModelPolicyClient(spec, backend, encoder)
