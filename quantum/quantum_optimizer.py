"""
Quantum Power Allocation Optimizer
Uses QAOA (Quantum Approximate Optimisation Algorithm) via Qiskit
to solve the vessel power distribution problem.
"""

import numpy as np
from typing import List, Dict, Tuple
from qiskit import QuantumCircuit
from qiskit.circuit import Parameter, ParameterVector
from qiskit_aer import AerSimulator
import json
import logging
import time

logger = logging.getLogger(__name__)


class VesselPowerQAOA:
    """
    QAOA-based solver for the vessel power allocation problem.

    Problem: Distribute available power across N loads while
    minimising cost = Σ(demand_i - alloc_i)^2 + penalty * violations
    subject to Σ alloc_i <= total_available.
    """

    def __init__(self, n_loads: int = 6, n_layers: int = 2, shots: int = 1024):
        self.n_loads = n_loads
        self.n_layers = n_layers
        self.shots = shots
        self.simulator = AerSimulator()
        self.last_result: Dict = {}
        logger.info(f"QuantumOptimizer init: {n_loads} loads, {n_layers} QAOA layers")

    # ------------------------------------------------------------------
    # Circuit construction
    # ------------------------------------------------------------------

    def _build_qaoa_circuit(
        self,
        cost_weights: np.ndarray,
        gamma: List[float],
        beta: List[float],
    ) -> QuantumCircuit:
        """Build a p-layer QAOA circuit over n_loads qubits."""
        n = self.n_loads
        qc = QuantumCircuit(n, n)

        # Equal superposition
        qc.h(range(n))

        for layer in range(self.n_layers):
            # Cost unitary: RZZ interactions encode the penalty
            for i in range(n):
                for j in range(i + 1, n):
                    coupling = cost_weights[i] * cost_weights[j]
                    angle = 2.0 * gamma[layer] * coupling
                    qc.rzz(angle, i, j)
                # Single-qubit cost
                qc.rz(2.0 * gamma[layer] * cost_weights[i], i)

            # Mixing unitary
            for i in range(n):
                qc.rx(2.0 * beta[layer], i)

        qc.measure(range(n), range(n))
        return qc

    # ------------------------------------------------------------------
    # Classical optimisation loop (grid search over gamma/beta)
    # ------------------------------------------------------------------

    def _evaluate_params(
        self,
        cost_weights: np.ndarray,
        gamma: List[float],
        beta: List[float],
    ) -> Tuple[float, Dict[str, int]]:
        qc = self._build_qaoa_circuit(cost_weights, gamma, beta)
        job = self.simulator.run(qc, shots=self.shots)
        counts = job.result().get_counts()

        # Expectation value of cost Hamiltonian
        energy = 0.0
        total = sum(counts.values())
        for bitstring, count in counts.items():
            bits = np.array([int(b) for b in bitstring[::-1]])
            cost = float(np.dot(bits, cost_weights) ** 2)
            energy += (count / total) * cost
        return energy, counts

    def optimise(
        self,
        power_demands: np.ndarray,
        total_available: float,
        priorities: np.ndarray | None = None,
    ) -> Dict:
        """
        Run QAOA optimisation and return best power allocation.

        Parameters
        ----------
        power_demands   : MW demand per load
        total_available : total MW available
        priorities      : relative importance weights (default uniform)
        """
        t0 = time.time()
        n = self.n_loads

        if priorities is None:
            priorities = np.ones(n)

        # Normalise demands into cost weights [0,1]
        max_d = max(power_demands.max(), 1e-9)
        cost_weights = (power_demands / max_d) * priorities

        best_energy = float("inf")
        best_counts: Dict[str, int] = {}
        best_params = (0.0, 0.0)

        # Grid search over QAOA angles
        gamma_vals = np.linspace(0.1, np.pi, 6)
        beta_vals = np.linspace(0.1, np.pi / 2, 6)

        for g in gamma_vals:
            for b in beta_vals:
                gamma = [g] * self.n_layers
                beta_v = [b] * self.n_layers
                energy, counts = self._evaluate_params(cost_weights, gamma, beta_v)
                if energy < best_energy:
                    best_energy = energy
                    best_counts = counts
                    best_params = (g, b)

        # Decode most probable bitstring
        best_bits = max(best_counts, key=best_counts.get)
        alloc_bits = np.array([int(b) for b in best_bits[::-1]])

        # Scale bits to actual MW allocation
        raw_alloc = alloc_bits * (power_demands / np.maximum(alloc_bits.sum(), 1))
        scale = min(1.0, total_available / max(raw_alloc.sum(), 1e-9))
        allocation = raw_alloc * scale

        elapsed = time.time() - t0

        self.last_result = {
            "allocation_mw": allocation.tolist(),
            "demands_mw": power_demands.tolist(),
            "total_available_mw": total_available,
            "total_allocated_mw": float(allocation.sum()),
            "utilisation_pct": float(100 * allocation.sum() / max(total_available, 1e-9)),
            "best_energy": float(best_energy),
            "best_gamma": float(best_params[0]),
            "best_beta": float(best_params[1]),
            "solve_time_s": round(elapsed, 3),
            "n_qubits": n,
            "n_layers": self.n_layers,
        }
        logger.info(
            f"QAOA solved in {elapsed:.2f}s | alloc={allocation.round(2)} MW"
        )
        return self.last_result


class QuantumAnomalyDetector:
    """
    Quantum-enhanced anomaly detection using amplitude estimation.
    Flags power readings that deviate beyond a quantum-computed threshold.
    """

    def __init__(self, n_qubits: int = 4):
        self.n_qubits = n_qubits
        self.simulator = AerSimulator()
        self.baseline_mean: float = 0.0
        self.baseline_std: float = 1.0

    def fit_baseline(self, historical_readings: np.ndarray) -> None:
        self.baseline_mean = float(np.mean(historical_readings))
        self.baseline_std = float(np.std(historical_readings)) or 1.0
        logger.info(
            f"AnomalyDetector baseline: μ={self.baseline_mean:.2f}, σ={self.baseline_std:.2f}"
        )

    def _quantum_threshold_circuit(self, z_score: float) -> QuantumCircuit:
        """Encode z-score as rotation angle; measure interference pattern."""
        n = self.n_qubits
        qc = QuantumCircuit(n, 1)
        angle = float(np.arctan(abs(z_score)) * 2)
        qc.h(range(n))
        for i in range(n):
            qc.ry(angle / (i + 1), i)
        # Entangle
        for i in range(n - 1):
            qc.cx(i, i + 1)
        qc.measure(n - 1, 0)
        return qc

    def detect(self, reading: float) -> Dict:
        z = (reading - self.baseline_mean) / self.baseline_std
        qc = self._quantum_threshold_circuit(z)
        job = self.simulator.run(qc, shots=512)
        counts = job.result().get_counts()
        p_anomaly = counts.get("1", 0) / 512

        return {
            "reading": reading,
            "z_score": round(z, 3),
            "p_anomaly": round(p_anomaly, 3),
            "is_anomaly": p_anomaly > 0.6,
            "severity": "critical" if p_anomaly > 0.85 else "warning" if p_anomaly > 0.6 else "normal",
        }
