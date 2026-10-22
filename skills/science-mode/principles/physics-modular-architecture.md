---
name: principle-physics-modular-architecture
description: "Decompose computational science code by physics phenomena. Isolate pure physical laws, operators, rate equations, and equations of state into standalone, stateless modules decoupled from time steppers, grids, and I/O so external solvers can call them directly."
disable-model-invocation: true
---

# Principle: Physics-Modular Architecture

Isolate pure physical laws, equations of state, forces, and state derivatives into dedicated, stateless modules completely decoupled from numerical time integrators, spatial mesh structures, and simulation I/O.

When physical models are tightly coupled to specific time steppers or simulation loops, they cannot be reused, independently tested, or called by other codes.

## When it applies

- Implementing or refactoring any physical law, force formula, equation of state (EOS), chemical kinetics rate law, or constitutive equation.
- Structuring scientific packages, solvers, and simulation pipelines.
- Building domain solvers (astrophysics, fluid mechanics, quantum mechanics, solid mechanics, molecular dynamics).

## Rules

1. **Strict Separation of Physics from Numerics**:
   - **Physics Layer (`physics/`)**: Pure functions that compute state derivatives $\frac{d\mathbf{y}}{dt}$, accelerations $\mathbf{a}(\mathbf{r}, m)$, fluxes $\mathbf{F}(\mathbf{u})$, or stresses $\boldsymbol{\sigma}(\boldsymbol{\varepsilon})$. They contain zero time-stepping logic, zero mesh allocation, and zero disk I/O.
   - **Numerics Layer (`numerics/`)**: Generalized numerical algorithms (Runge-Kutta, symplectic Leapfrog, GMRES, Newton-Raphson, Adams-Bashforth) that accept an arbitrary callable physics function/operator.
   - **Geometry & Mesh Layer (`mesh/` or `geometry/`)**: Coordinate systems, spatial discretization grids, boundary shape definitions.
   - **Driver / Simulation Layer (`sim/` or `driver.py`)**: Assembles the physics operator and numeric stepper, controls the simulation time loop, and handles checkpointing.

2. **Driver-Agnostic, Callable Interfaces**:
   Physics routines must be directly callable by external codes with standard array or primitive inputs:
   ```python
   # Pure physics function: stateless, driver-agnostic
   def gravitational_acceleration(
       positions: np.ndarray, 
       masses: np.ndarray, 
       G: float = 1.0, 
       softening: float = 0.0
   ) -> np.ndarray:
       r"""
       Compute pairwise Newtonian gravitational accelerations.
       Can be invoked by any integrator (Leapfrog, RK4, Hermite, adaptive).
       """
   ```

3. **No Embedded Global State**:
   Physics modules must not rely on hidden global simulation states, singletons, or implicit environment variables. All physical parameters ($G$, $c$, $\gamma$, material coefficients) must be passed explicitly or bundled in immutable parameter dataclasses.

4. **Independent Unit Testability**:
   Every physics module must have dedicated unit tests verifying its mathematical output against exact analytical evaluations or limit states without running a time loop or initializing a full simulation environment.

## Anti-Pattern vs. Compliant Architecture

### Anti-Pattern: Monolithic Simulation Class
```python
# BAD: Physics (gravitational force), numerical time integration (Euler/Verlet),
# and file I/O are inseparable. External codes cannot call just the gravitational law.
class MonolithicSimulation:
    def __init__(self, n_particles):
        self.positions = np.zeros((n_particles, 3))
        self.velocities = np.zeros((n_particles, 3))
        
    def step_and_save(self, dt, filename):
        # Entangled acceleration calculation + time step + file write
        for i in range(len(self.positions)):
            # Force logic buried inside stepper...
            ...
        self.positions += self.velocities * dt
        with open(filename, "a") as f:
            f.write(str(self.positions))
```

### Compliant: Physics-Modular Architecture
```python
# GOOD: 
# 1. Physics module (reusable by any code or integrator)
# physics/gravity.py
def gravitational_accelerations(positions: np.ndarray, masses: np.ndarray, G: float) -> np.ndarray:
    r"""Stateless physics operator: a_i = -G \sum_j m_j (r_i - r_j) / |r_i - r_j|^3."""
    ...
    return acc

# 2. Reusable numerical stepper
# numerics/symplectic.py
def leapfrog_step(q: np.ndarray, v: np.ndarray, dt: float, accel_func: Callable[[np.ndarray], np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    r"""Symplectic Drift-Kick-Drift step accepting any acceleration physics function."""
    q_half = q + 0.5 * dt * v
    a_mid = accel_func(q_half)
    v_next = v + dt * a_mid
    q_next = q_half + 0.5 * dt * v_next
    return q_next, v_next

# 3. External codes can now import either component independently!
from physics.gravity import gravitational_accelerations
from numerics.symplectic import leapfrog_step
```
