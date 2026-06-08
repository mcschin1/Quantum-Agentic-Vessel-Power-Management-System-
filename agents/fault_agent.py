"""
Fault Detection & Prediction Agent
Monitors all power system measurements, uses the QuantumAnomalyDetector
to identify anomalies, and raises actionable alerts.
"""

import asyncio
import random
import time
import logging
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Deque, Optional
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from quantum.quantum_optimizer import QuantumAnomalyDetector

logger = logging.getLogger(__name__)


class AlertLevel:
    INFO     = "info"
    WARNING  = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class Alert:
    id: str
    level: str
    component: str
    message: str
    value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "level": self.level,
            "component": self.component,
            "message": self.message,
            "value": round(self.value, 3),
            "threshold": round(self.threshold, 3),
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


class FaultDetectionAgent:
    """
    Quantum-enhanced fault detection for the vessel power system.

    Monitors:
      - Bus voltage (each zone)
      - Generator output current
      - Power factor per feeder
      - Frequency deviation
      - Thermal readings (transformer, switchboard)
    """

    HISTORY_LEN = 200   # samples to keep per channel

    def __init__(self):
        # Anomaly detectors per channel
        self.detectors: Dict[str, QuantumAnomalyDetector] = {}
        self.histories: Dict[str, Deque[float]] = {}
        self.alerts: List[Alert] = []
        self._alert_counter = 0
        self.tick: int = 0
        self._running: bool = False
        self._channels_defined: bool = False
        logger.info("FaultDetectionAgent initialised")

    # ------------------------------------------------------------------
    # Channel registration
    # ------------------------------------------------------------------

    def register_channel(self, name: str, baseline: np.ndarray) -> None:
        det = QuantumAnomalyDetector(n_qubits=4)
        det.fit_baseline(baseline)
        self.detectors[name] = det
        self.histories[name] = deque(maxlen=self.HISTORY_LEN)
        logger.debug(f"Registered channel: {name}")

    def _init_channels(self) -> None:
        """Initialise monitoring channels with synthetic baselines."""
        channel_specs = {
            # name: (mean, std)
            "bus_v_zone1":     (690.0, 5.0),
            "bus_v_zone2":     (690.0, 5.0),
            "bus_v_zone3":     (440.0, 4.0),
            "gen1_current_a":  (350.0, 20.0),
            "gen2_current_a":  (350.0, 20.0),
            "gen3_current_a":  (280.0, 18.0),
            "frequency_hz":    (60.0,  0.15),
            "pf_main_bus":     (0.92,  0.03),
            "temp_sw_main":    (45.0,  3.0),
            "temp_transformer":(55.0,  4.0),
        }
        rng = np.random.default_rng(42)
        for name, (mu, sigma) in channel_specs.items():
            baseline = rng.normal(mu, sigma, 100)
            self.register_channel(name, baseline)
        self._channels_defined = True
        logger.info(f"Initialised {len(channel_specs)} monitoring channels")

    # ------------------------------------------------------------------
    # Measurement simulation
    # ------------------------------------------------------------------

    def _simulate_reading(self, channel: str) -> float:
        """Generate a realistic (mostly normal) sensor reading."""
        specs = {
            "bus_v_zone1":     (690.0, 5.0),
            "bus_v_zone2":     (690.0, 5.0),
            "bus_v_zone3":     (440.0, 4.0),
            "gen1_current_a":  (350.0, 20.0),
            "gen2_current_a":  (350.0, 20.0),
            "gen3_current_a":  (280.0, 18.0),
            "frequency_hz":    (60.0,  0.15),
            "pf_main_bus":     (0.92,  0.03),
            "temp_sw_main":    (45.0,  3.0),
            "temp_transformer":(55.0,  4.0),
        }
        mu, sigma = specs.get(channel, (100.0, 5.0))
        # 3% chance of injecting an anomaly
        if random.random() < 0.03:
            return mu + random.choice([-1, 1]) * sigma * random.uniform(3.5, 6.0)
        return random.gauss(mu, sigma)

    # ------------------------------------------------------------------
    # Alert management
    # ------------------------------------------------------------------

    def _raise_alert(self, result: Dict, channel: str) -> Optional[Alert]:
        if not result["is_anomaly"]:
            return None

        # Deduplicate: suppress if same channel already has unack'd alert
        for a in self.alerts[-20:]:
            if a.component == channel and not a.acknowledged:
                return None

        self._alert_counter += 1
        level = AlertLevel.CRITICAL if result["severity"] == "critical" else AlertLevel.WARNING
        alert = Alert(
            id=f"ALT-{self._alert_counter:04d}",
            level=level,
            component=channel,
            message=f"Quantum anomaly detected on {channel}: p={result['p_anomaly']:.2f}, z={result['z_score']:.2f}",
            value=result["reading"],
            threshold=result["z_score"],
        )
        self.alerts.append(alert)
        logger.warning(f"[{level.upper()}] {alert.message}")
        return alert

    def acknowledge_alert(self, alert_id: str) -> bool:
        for a in self.alerts:
            if a.id == alert_id:
                a.acknowledged = True
                return True
        return False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, dt_s: float = 1.0) -> None:
        if not self._channels_defined:
            self._init_channels()
        self._running = True

        while self._running:
            for channel, detector in self.detectors.items():
                reading = self._simulate_reading(channel)
                self.histories[channel].append(reading)
                result = detector.detect(reading)
                self._raise_alert(result, channel)

            self.tick += 1
            await asyncio.sleep(dt_s)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict:
        latest_readings = {
            ch: round(list(hist)[-1], 3) if hist else 0.0
            for ch, hist in self.histories.items()
        }
        active_alerts = [a.to_dict() for a in self.alerts[-50:] if not a.acknowledged]
        return {
            "channels": list(self.detectors.keys()),
            "latest_readings": latest_readings,
            "active_alerts": active_alerts,
            "total_alerts": len(self.alerts),
            "tick": self.tick,
        }
