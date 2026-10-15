"""Match ordered sensor streams without reusing samples."""

from bisect import bisect_left
from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence


@dataclass(frozen=True)
class SyncedIndices:
    anchor_index: int
    stream_indices: Mapping[str, int]


def synchronize_timestamps(
    anchors: Sequence[int], streams: Mapping[str, Sequence[int]], tolerance_ns: int
) -> List[SyncedIndices]:
    if tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")
    if not streams:
        raise ValueError("at least one stream is required")
    for name, values in (("anchors", anchors), *streams.items()):
        if not name or any(value < 0 for value in values):
            raise ValueError("stream names and timestamps must be valid")
        if any(left >= right for left, right in zip(values, values[1:])):
            raise ValueError("timestamps must be strictly increasing")

    next_indices = {name: 0 for name in streams}
    matches = []
    for anchor_index, anchor in enumerate(anchors):
        selected: Dict[str, int] = {}
        for name, values in streams.items():
            start = next_indices[name]
            position = bisect_left(values, anchor, lo=start)
            candidates = [index for index in (position - 1, position) if start <= index < len(values)]
            if not candidates:
                break
            nearest = min(candidates, key=lambda index: (abs(values[index] - anchor), index))
            if abs(values[nearest] - anchor) > tolerance_ns:
                break
            selected[name] = nearest
        if len(selected) == len(streams):
            matches.append(SyncedIndices(anchor_index, selected))
            for name, index in selected.items():
                next_indices[name] = index + 1
    return matches
