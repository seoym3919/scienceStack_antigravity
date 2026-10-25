---
name: precision-audit
description: Audit floating-point precision: float32 vs float64, condition-number amplification, mixed-precision drift. Use when changing precision or when results differ across platforms or precisions.
argument-hint: "<file_or_dir>"
---

# Precision-Aware Numerical Auditing Framework

In scientific computing, floating-point precision is not merely an optimization knob; inadequate precision alters the mathematical character of solutions.

---

## 1. Machine Epsilon ($\epsilon_{\text{mach}}$) & Precision Limits

| IEEE-754 Format | Bits | Sign / Exponent / Mantissa | Significant Decimal Digits | $\epsilon_{\text{mach}}$ |
| :--- | :--- | :--- | :--- | :--- |
| `float16` (half) | 16 | 1 / 5 / 10 | $\approx 3.3$ | $9.77 \times 10^{-4}$ |
| `bfloat16` (brain) | 16 | 1 / 8 / 7 | $\approx 2.4$ | $7.81 \times 10^{-3}$ |
| `float32` (single) | 32 | 1 / 8 / 23 | $\approx 7.2$ | $1.19 \times 10^{-7}$ |
| `float64` (double) | 64 | 1 / 11 / 52 | $\approx 15.9$ | $2.22 \times 10^{-16}$ |

---

## 2. Where Single Precision (`float32`) Fails in Science

1. **Phase Error & Secular Drift in Celestial Mechanics**:
   - In orbital simulations, a single precision roundoff of $\sim 10^{-7}$ per time-step accumulates to $O(1)$ radian phase error within $10^5$ steps.
   - **Rule**: All time variables ($t, \Delta t$), orbital state vectors ($\mathbf{r}, \mathbf{v}$), and planetary masses must remain strictly `float64`.
2. **Matrix Condition Number Amplification**:
   - In linear systems $\mathbf{A}\mathbf{x} = \mathbf{b}$, the relative error in $\mathbf{x}$ is bounded by:
     \begin{equation}
         \frac{\|\Delta \mathbf{x}\|}{\|\mathbf{x}\|} \le \kappa(\mathbf{A}) \frac{\|\Delta \mathbf{b}\|}{\|\mathbf{b}\|}
     \end{equation}
   - If $\kappa(\mathbf{A}) \approx 10^7$, solving in `float32` loses all 7 significant digits, returning pure numerical garbage.
   - **Rule**: If $\kappa(\mathbf{A}) > 10^3$, do not solve in single precision without iterative refinement.
3. **Catastrophic Cancellation in Finite Differences**:
   - Numerical differentiation $f'(x) \approx \frac{f(x+h) - f(x)}{h}$ has an optimal step $h \approx \sqrt{\epsilon_{\text{mach}}}$.
   - In `float32`, $\sqrt{\epsilon} \approx 3 \times 10^{-4}$, limiting accuracy to only $\sim 3$ digits.
   - In `float64`, $\sqrt{\epsilon} \approx 1.5 \times 10^{-8}$, yielding $\sim 8$ digits.

---

## 3. Auditing Checklist

- [ ] Are time accumulators (`t += dt`) stored in `float64`?
- [ ] Are coordinates in large spatial domains (e.g., Solar System in meters, cosmologic boxes in Mpc) stored in `float64`?
- [ ] Are matrix condition numbers estimated using `np.linalg.cond(A)` or 1-norm estimators?
- [ ] If using JAX, is double precision enabled via `jax.config.update("jax_enable_x64", True)`?
- [ ] If mixed precision is used for speed, is iterative refinement applied:
  \begin{equation}
      \mathbf{r} = \mathbf{b} - \mathbf{A} \mathbf{x}_0 \quad (\text{double}), \quad \mathbf{A} \mathbf{d} = \mathbf{r} \quad (\text{single}), \quad \mathbf{x}_1 = \mathbf{x}_0 + \mathbf{d} \quad (\text{double})
  \end{equation}
