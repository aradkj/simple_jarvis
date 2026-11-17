"""Cinematic Voice Visualizer Widget for JARVIS.

Provides a high-performance, GPU-accelerated (via QPainter antialiasing) dark holographic
energy reactor and audio waveform visualizer that reacts in real-time to genuine microphone
input levels (RMS) and voice pipeline state transitions.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from tools.voice.models import VoiceState


class JarvisVisualizerWidget(QWidget):
    """Futuristic cinematic reactor widget with audio-reactive animations and real mic RMS metering."""

    state_changed = Signal(str)
    level_updated = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(280, 200)

        # State tracking
        self._voice_state: str = VoiceState.IDLE.value
        self._target_mic_level: float = 0.0
        self._current_mic_level: float = 0.0
        self._status_text: str = 'STANDBY ("HEY JARVIS")'

        # Animation parameters
        self._phase: float = 0.0
        self._rotation_deg: float = 0.0
        self._pulse: float = 0.0
        self._pulse_dir: float = 1.0

        # High-performance 30 FPS render timer (~33ms)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_animation_frame)
        self._anim_timer.start(33)

        # Connect internal Qt signals for thread-safe cross-thread updates
        self.level_updated.connect(self._apply_level_update)
        self.state_changed.connect(self._apply_state_change)

    def set_voice_state(self, state: VoiceState | str, status_text: str | None = None) -> None:
        """Thread-safe update of current voice state and status text."""
        val = state.value if isinstance(state, VoiceState) else str(state).lower()
        self.state_changed.emit(val)
        if status_text:
            self._status_text = status_text

    def _apply_state_change(self, state_val: str) -> None:
        self._voice_state = state_val
        if state_val == VoiceState.IDLE.value:
            self._status_text = 'STANDBY ("HEY JARVIS")'
        elif state_val == VoiceState.LISTENING.value:
            self._status_text = "LISTENING FOR SPEECH..."
        elif state_val == VoiceState.RECORDING.value:
            self._status_text = "RECORDING SPEECH (LIVE MIC)"
        elif state_val == VoiceState.TRANSCRIBING.value:
            self._status_text = "TRANSCRIBING AUDIO..."
        elif state_val == VoiceState.THINKING.value:
            self._status_text = "ANALYZING INTENT & REASONING..."
        elif state_val == VoiceState.SPEAKING.value:
            self._status_text = "JARVIS SPEAKING (GEORGE NEURAL)"
        elif state_val == VoiceState.WAITING.value:
            self._status_text = "WAITING FOR FOLLOW-UP..."
        elif state_val == VoiceState.INTERRUPTED.value:
            self._status_text = "BARGE-IN INTERRUPTED"
        elif state_val == VoiceState.SESSION_ACTIVATING.value:
            self._status_text = "ACTIVATING PERSISTENT SESSION..."
        elif state_val == VoiceState.UNDERSTANDING.value:
            self._status_text = "UNDERSTANDING CONVERSATION CONTEXT..."
        elif state_val == VoiceState.GENERATING_RESPONSE.value:
            self._status_text = "GENERATING RESPONSE..."
        elif state_val == VoiceState.SESSION_STOPPING.value:
            self._status_text = "STOPPING LISTENING SESSION..."
        elif state_val == VoiceState.SESSION_ENDED.value:
            self._status_text = 'SESSION ENDED — STANDBY ("HEY JARVIS")'
        elif state_val == VoiceState.ERROR.value:
            self._status_text = "VOICE INPUT ERROR"
        elif state_val == VoiceState.MUTED.value:
            self._status_text = "MICROPHONE MUTED"
        self.update()

    def set_mic_level(self, level: float) -> None:
        """Thread-safe update of microphone RMS input level (0.0 to 1.0)."""
        clamped = max(0.0, min(1.0, float(level)))
        self.level_updated.emit(clamped)

    def _apply_level_update(self, level: float) -> None:
        self._target_mic_level = level

    def set_status_text(self, text: str) -> None:
        """Set custom status badge description."""
        self._status_text = text
        self.update()

    def get_voice_state(self) -> str:
        """Return the current voice state string."""
        return self._voice_state

    def _on_animation_frame(self) -> None:
        """Tick animation variables for continuous cinematic movement."""
        self._phase += 0.08
        if self._phase > 2 * math.pi:
            self._phase -= 2 * math.pi

        self._rotation_deg = (self._rotation_deg + 1.5) % 360.0

        # Smooth pulse
        self._pulse += 0.04 * self._pulse_dir
        if self._pulse > 1.0:
            self._pulse = 1.0
            self._pulse_dir = -1.0
        elif self._pulse < 0.0:
            self._pulse = 0.0
            self._pulse_dir = 1.0

        # Smooth mic level decay/attack (fast attack, smooth release)
        if self._target_mic_level > self._current_mic_level:
            self._current_mic_level += (self._target_mic_level - self._current_mic_level) * 0.4
        else:
            self._current_mic_level += (self._target_mic_level - self._current_mic_level) * 0.15

        self.update()

    def _get_theme_palette(self) -> dict[str, Any]:
        """Return color palette and configuration based on current voice state."""
        state = self._voice_state

        if state == VoiceState.RECORDING.value:
            # Active user speech capture: Intense electric cyan / neon teal
            return {
                "core_color": QColor(0, 229, 255),
                "glow_color": QColor(0, 200, 255, 120),
                "ring_color": QColor(0, 240, 255, 200),
                "meter_color": QColor(0, 229, 255),
                "speed_mult": 2.2,
                "spike_amp": 28.0,
            }
        elif state == VoiceState.LISTENING.value:
            # Active listening: Vibrant cyan
            return {
                "core_color": QColor(0, 180, 255),
                "glow_color": QColor(0, 150, 255, 80),
                "ring_color": QColor(0, 210, 255, 160),
                "meter_color": QColor(0, 210, 255),
                "speed_mult": 1.2,
                "spike_amp": 12.0,
            }
        elif state == VoiceState.TRANSCRIBING.value:
            # Transcribing: High-speed tech gyro / light blue
            return {
                "core_color": QColor(100, 200, 255),
                "glow_color": QColor(50, 150, 255, 100),
                "ring_color": QColor(120, 220, 255, 220),
                "meter_color": QColor(100, 200, 255),
                "speed_mult": 3.0,
                "spike_amp": 10.0,
            }
        elif state == VoiceState.THINKING.value:
            # Agent reasoning: Neural violet/purple to cyan
            return {
                "core_color": QColor(168, 85, 247),
                "glow_color": QColor(121, 40, 202, 110),
                "ring_color": QColor(192, 132, 252, 190),
                "meter_color": QColor(168, 85, 247),
                "speed_mult": 1.8,
                "spike_amp": 8.0,
            }
        elif state == VoiceState.SPEAKING.value:
            # JARVIS speaking: Majestic golden amber & cyan acoustic undulation
            return {
                "core_color": QColor(255, 184, 0),
                "glow_color": QColor(255, 150, 0, 100),
                "ring_color": QColor(255, 200, 50, 210),
                "meter_color": QColor(255, 184, 0),
                "speed_mult": 2.0,
                "spike_amp": 22.0,
            }
        elif state == VoiceState.WAITING.value:
            # Conversational wait: Soft cyan halo
            return {
                "core_color": QColor(56, 189, 248),
                "glow_color": QColor(14, 165, 233, 70),
                "ring_color": QColor(125, 211, 252, 150),
                "meter_color": QColor(56, 189, 248),
                "speed_mult": 0.9,
                "spike_amp": 6.0,
            }
        elif state == VoiceState.INTERRUPTED.value:
            # Barge-in: Vivid amber-red alert pulse
            return {
                "core_color": QColor(255, 87, 34),
                "glow_color": QColor(255, 87, 34, 130),
                "ring_color": QColor(255, 110, 64, 220),
                "meter_color": QColor(255, 87, 34),
                "speed_mult": 2.8,
                "spike_amp": 20.0,
            }
        elif state == VoiceState.ERROR.value:
            # Error condition: Crimson warning
            return {
                "core_color": QColor(244, 63, 94),
                "glow_color": QColor(225, 29, 72, 100),
                "ring_color": QColor(251, 113, 133, 180),
                "meter_color": QColor(244, 63, 94),
                "speed_mult": 0.8,
                "spike_amp": 4.0,
            }
        elif state == VoiceState.MUTED.value:
            # Muted: Dim gray
            return {
                "core_color": QColor(100, 116, 139),
                "glow_color": QColor(71, 85, 105, 50),
                "ring_color": QColor(148, 163, 184, 100),
                "meter_color": QColor(100, 116, 139),
                "speed_mult": 0.2,
                "spike_amp": 0.0,
            }
        else:
            # Default IDLE standby: Deep sleek electric cyan
            return {
                "core_color": QColor(0, 229, 255),
                "glow_color": QColor(0, 200, 255, 60),
                "ring_color": QColor(0, 229, 255, 140),
                "meter_color": QColor(0, 229, 255),
                "speed_mult": 1.0,
                "spike_amp": 8.0,
            }

    def paintEvent(self, event: Any) -> None:
        """Render the dark cinematic holographic reactor and real-time audio meter."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # 1. Dark Futuristic Backdrop (#070B14 gradient)
        bg_gradient = QRadialGradient(width / 2, height / 2 - 14, min(width, height) * 0.7)
        bg_gradient.setColorAt(0.0, QColor(11, 20, 38, 230))
        bg_gradient.setColorAt(0.6, QColor(7, 11, 20, 245))
        bg_gradient.setColorAt(1.0, QColor(4, 7, 13, 255))
        painter.fillRect(self.rect(), QBrush(bg_gradient))

        # Thin cinematic tech border
        painter.setPen(QPen(QColor(0, 229, 255, 35), 1))
        painter.drawRoundedRect(QRectF(1, 1, width - 2, height - 2), 8, 8)

        pal = self._get_theme_palette()
        center_x = width / 2.0
        center_y = (height - 38) / 2.0  # Reserve bottom 38px for meter & status
        base_radius = min(width, height - 40) * 0.26

        # 2. Outer Glow Halo
        glow_rad = base_radius * (1.6 + self._pulse * 0.15 + self._current_mic_level * 0.4)
        halo_gradient = QRadialGradient(center_x, center_y, glow_rad)
        halo_gradient.setColorAt(0.0, pal["glow_color"])
        halo_gradient.setColorAt(
            0.5,
            QColor(
                pal["glow_color"].red(), pal["glow_color"].green(), pal["glow_color"].blue(), 25
            ),
        )
        halo_gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(halo_gradient))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(center_x, center_y), glow_rad, glow_rad)

        # 3. Rotating Tech Reticle / Orbiting Arcs
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(self._rotation_deg * pal["speed_mult"])

        reticle_pen = QPen(pal["ring_color"], 1.5, Qt.PenStyle.DashLine)
        painter.setPen(reticle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        reticle_r = base_radius * 1.35
        painter.drawEllipse(QPointF(0, 0), reticle_r, reticle_r)

        # Orbiting accent nodes
        for angle_deg in (0, 90, 180, 270):
            rad = math.radians(angle_deg)
            nx = reticle_r * math.cos(rad)
            ny = reticle_r * math.sin(rad)
            painter.setBrush(QBrush(pal["core_color"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(nx, ny), 3, 3)

        painter.restore()

        # 4. Audio-Reactive Waveform Ring
        # Renders 48 radial nodes modulated by microphone RMS level
        num_points = 48
        wave_path = QPainterPath()
        points: list[QPointF] = []

        rms_boost = self._current_mic_level * pal["spike_amp"]
        for i in range(num_points):
            angle = (i / num_points) * 2 * math.pi
            # Dual frequency harmonic wave modulated by live audio RMS
            wave_mod = (
                math.sin(angle * 4 + self._phase * pal["speed_mult"]) * 0.6
                + math.cos(angle * 7 - self._phase * 1.5) * 0.4
            )
            r = base_radius + wave_mod * (3.0 + rms_boost)
            px = center_x + r * math.cos(angle)
            py = center_y + r * math.sin(angle)
            points.append(QPointF(px, py))

        if points:
            wave_path.moveTo(points[0])
            for pt in points[1:]:
                wave_path.lineTo(pt)
            wave_path.closeSubpath()

            # Fill with subtle glow
            wave_grad = QRadialGradient(center_x, center_y, base_radius * 1.2)
            c = pal["core_color"]
            wave_grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 50))
            wave_grad.setColorAt(0.8, QColor(c.red(), c.green(), c.blue(), 20))
            wave_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(wave_grad))

            wave_pen = QPen(pal["core_color"], 2.2)
            painter.setPen(wave_pen)
            painter.drawPath(wave_path)

        # 5. Inner Core Reactor
        core_r = base_radius * (0.55 + self._pulse * 0.08 + self._current_mic_level * 0.15)
        core_grad = QRadialGradient(center_x, center_y, core_r)
        core_grad.setColorAt(0.0, QColor(255, 255, 255, 240))
        core_grad.setColorAt(0.4, pal["core_color"])
        core_grad.setColorAt(
            1.0,
            QColor(
                pal["core_color"].red(), pal["core_color"].green(), pal["core_color"].blue(), 40
            ),
        )

        painter.setBrush(QBrush(core_grad))
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1.2))
        painter.drawEllipse(QPointF(center_x, center_y), core_r, core_r)

        # 6. Real-Time Microphone Level Indicator Bar (Bottom)
        meter_y = height - 26
        meter_width = min(260, width - 40)
        meter_x = (width - meter_width) / 2.0
        meter_h = 6

        # Meter background track
        painter.setBrush(QBrush(QColor(20, 30, 48, 180)))
        painter.setPen(QPen(QColor(0, 229, 255, 40), 1))
        painter.drawRoundedRect(QRectF(meter_x, meter_y, meter_width, meter_h), 3, 3)

        # Active RMS level bar
        fill_w = max(2.0, meter_width * self._current_mic_level)
        bar_grad = QLinearGradient(meter_x, meter_y, meter_x + fill_w, meter_y)
        bar_grad.setColorAt(0.0, QColor(0, 229, 255))
        bar_grad.setColorAt(0.7, QColor(0, 255, 180))
        bar_grad.setColorAt(1.0, pal["meter_color"])

        painter.setBrush(QBrush(bar_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(meter_x, meter_y, fill_w, meter_h), 3, 3)

        # 7. Status Text Label
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.setPen(QPen(pal["core_color"]))
        status_rect = QRectF(10, height - 44, width - 20, 16)
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignCenter, self._status_text)
