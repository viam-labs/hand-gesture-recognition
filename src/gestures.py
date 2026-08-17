"""Gesture stabilization — pure logic, no Viam or MediaPipe imports.

MediaPipe classifies every frame independently, so a hand moving between poses
transiently reads as other gestures. Feeding that straight to the arm means the
arm lunges on a single bad frame. Two filters fix it:

1. **Hold.** A gesture must be the top result continuously for ``hold_ms``
   before it counts as stable. The window is wall-clock rather than a frame
   count because the caller's poll rate is not ours to control — the reactor's
   ``poll_interval_ms`` would otherwise silently redefine "N frames".

2. **Edge trigger.** A stable gesture fires exactly once. Holding the pose does
   not re-fire it; the hand must clear (or, with ``require_clear`` off, change to
   a different gesture) before anything else can trigger. Without this, holding
   an open palm replays the session every ``cooldown_sec`` forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GestureStabilizer:
    """Turns a noisy per-frame gesture stream into single-shot triggers.

    Feed every observation to :meth:`update`. It returns a label on exactly the
    call where that gesture becomes newly stable, and ``None`` every other time.

    Args:
        hold_ms: How long a gesture must persist before it is considered stable.
        clear_ms: How long "no gesture" must persist before the latch releases
            and a new trigger is allowed.
        require_clear: When ``True`` (default) the hand must clear between
            triggers, so switching straight from one gesture to another fires
            nothing. When ``False``, a different stable gesture fires
            immediately. ``True`` is the safer default: it forces a deliberate
            reset between arm motions.
    """

    hold_ms: float = 400.0
    clear_ms: float = 300.0
    require_clear: bool = True

    _candidate: Optional[str] = field(default=None, init=False)
    _since: float = field(default=0.0, init=False)
    _latched: Optional[str] = field(default=None, init=False)
    _started: bool = field(default=False, init=False)

    def update(self, label: Optional[str], now: float) -> Optional[str]:
        """Observe one frame's classification.

        Args:
            label: The top gesture, or ``None`` for no hand / no gesture.
                MediaPipe's own ``"None"`` category must be mapped to ``None``
                by the caller.
            now: Monotonic timestamp in seconds.

        Returns:
            The label, on the single call where it becomes newly stable.
            ``None`` otherwise.
        """
        if label != self._candidate or not self._started:
            self._candidate = label
            self._since = now
            self._started = True

        held_ms = (now - self._since) * 1000.0

        if label is None:
            # Sustained absence releases the latch, re-arming the next trigger.
            if held_ms >= self.clear_ms:
                self._latched = None
            return None

        if held_ms < self.hold_ms:
            return None

        if self._latched == label:
            return None  # already fired; holding the pose must not re-fire

        if self.require_clear and self._latched is not None:
            return None  # a different gesture is latched and the hand never cleared

        self._latched = label
        return label

    def is_stable(self, label: Optional[str], now: float) -> bool:
        """Whether ``label`` is currently the held-long-enough candidate.

        Read-only — does not advance state. Used to decide how a hand is
        annotated in the camera stream, separately from whether it triggers.
        """
        if label is None or label != self._candidate:
            return False
        return (now - self._since) * 1000.0 >= self.hold_ms

    @property
    def latched(self) -> Optional[str]:
        """The gesture that most recently fired, or ``None`` if cleared."""
        return self._latched

    def reset(self) -> None:
        """Drop all state. Call on reconfigure so stale latches do not survive."""
        self._candidate = None
        self._since = 0.0
        self._latched = None
        self._started = False
