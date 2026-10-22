---
name: principle-dimensional-discipline
description: "Enforce dimensional consistency and unit scaling before writing code. Enforce non-dimensionalization, type-level units, or unit assertions at system boundaries. Use when designing scientific APIs or modeling physical systems."
disable-model-invocation: true
---

# Principle: Dimensional Discipline

Every physical quantity carries dimensions $[M]^a [L]^b [T]^c [\Theta]^d \dots$. An equation with mismatched dimensions is mathematically false and physically impossible.

Dimensional errors cause silent bugs that can appear plausible while producing completely incorrect quantitative results.

## When it applies

- Designing functions, data structures, or classes representing physical or engineering quantities.
- Numerical simulation pipelines involving multiple physical scales (e.g. nanometers vs meters, femtoseconds vs seconds).
- Ingesting external scientific datasets or configuration files with varied units.

## Rules

1. **Perform Dimensional Analysis First**:
   Before writing code, verify that the left-hand side and right-hand side of every equality have identical physical dimensions:
   $$[LHS] = [RHS]$$
   Check that transcendental functions ($\exp(x)$, $\log(x)$, $\sin(x)$) take strictly dimensionless arguments:
   $$[\arg] = 1$$

2. **Prefer Non-Dimensionalization for Solvers**:
   Scale and non-dimensionalize governing equations before passing them to numerical integrators or linear solvers:
   - Identify characteristic scales ($L_0$, $T_0$, $V_0$, $M_0$).
   - Define dimensionless variables: $\tilde{x} = x / L_0$, $\tilde{t} = t / T_0$.
   - Express equations in terms of standard dimensionless numbers (Reynolds $Re$, Péclet $Pe$, Mach $Ma$, Knudsen $Kn$).
   - Solvers operate on dimensionless numbers of order $\mathcal{O}(1)$, eliminating catastrophic floating-point scaling issues. Redimensionalize only at reporting boundaries.

3. **Explicit Units in Variable Names or Type Annotations**:
   If quantities remain dimensional in code, encode the unit into the variable or parameter name:
   - Good: `pressure_pa`, `temperature_k`, `length_nm`, `velocity_m_per_s`, `dt_sec`.
   - Bad: `p`, `temp`, `length`, `v`, `dt` (ambiguous: are they SI, CGS, atomic units, or imperial?).

4. **Unit Conversions at Ingestion Boundaries**:
   Never scatter unit conversion constants ($10^{-3}$, $1.602 \times 10^{-19}$, $10^6$) across computation kernels.
   Parse and convert all inputs into a consistent internal unit system (standard SI or chosen atomic units) immediately upon ingestion.
   Assert or validate units with runtime checks or typed unit libraries (e.g. `pint`, `astropy.units`) where available.

5. **Dimensional Assertion Tests**:
   Write tests that verify invariance under unit rescaling: if all base units $[M], [L], [T]$ are scaled by arbitrary factors $\alpha, \beta, \gamma$, the resulting physical prediction must scale according to its known dimensional power law.
