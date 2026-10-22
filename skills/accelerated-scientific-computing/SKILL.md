---
name: accelerated-scientific-computing
description: Best practices, memory layouts, SIMD vectorization, and precision guards for high-performance scientific computing in C++, Fortran, Julia, and JAX. Use for /accelerated-scientific-computing, "C++ scientific code", "Fortran kernels", "Julia scientific computing", or "JAX GPU simulation".
---

# High-Performance & Multi-Language Scientific Computing

When engineering scientific solvers across compiled languages (C++, Fortran, Julia) or accelerated frameworks (JAX, CUDA):

---

## 1. Memory Layout & Cache Locality Discipline

The fundamental difference between programming languages in multi-dimensional array storage determines memory stride and cache hit rates:

| Language | Array Memory Layout | Fast Index Order (Contiguous) | Slow Index Order (Strided) |
| :--- | :--- | :--- | :--- |
| **C / C++** | **Row-Major** (C-order) | Rightmost index: `A[i][j][k++]` | Leftmost index: `A[i++][j][k]` |
| **Python / NumPy** | **Row-Major** (default) | Rightmost index: `A[i, j, k]` | Leftmost index: `A[k, j, i]` |
| **Fortran** | **Column-Major** (Fortran-order) | Leftmost index: `A(i++, j, k)` | Rightmost index: `A(i, j, k++)` |
| **Julia** | **Column-Major** (Fortran-order) | Leftmost index: `A[i++, j, k]` | Rightmost index: `A[i, j, k++]` |
| **MATLAB** | **Column-Major** (Fortran-order) | Leftmost index: `A(i++, j, k)` | Rightmost index: `A(i, j, k++)` |

### Loop Nesting Rule
- In **C++ / C / NumPy**: Always nest loops as:
  ```cpp
  for (int i = 0; i < N; ++i)
      for (int j = 0; j < M; ++j)
          C[i][j] = A[i][j] + B[i][j];  // Stride 1 in inner loop
  ```
- In **Fortran / Julia**: Always nest loops as:
  ```julia
  for j in 1:M
      for i in 1:N
          C[i, j] = A[i, j] + B[i, j]  # Stride 1 in inner loop
      end
  end
  ```
  *Inverting this nest causes strided memory access, cache eviction, and 10x-50x performance degradation.*

---

## 2. JAX & Autodiff Scientific Gotchas

1. **Default Single Precision (`float32`)**:
   - By default, JAX truncates all float literals and calculations to `float32`.
   - **Mandated Initialization**:
     ```python
     import jax
     jax.config.update("jax_enable_x64", True)
     ```
2. **Pure Functions & `vmap`**:
   - Physical state update functions must be purely functional (no in-place mutation of arrays):
     ```python
     # Bad:
     state[0] += dt * v
     # Correct:
     new_state = state.at[0].add(dt * v)
     ```
3. **Autodiff of Piecewise Physical Transitions**:
   - When taking analytical gradients of equations with branch cuts (e.g., flux limiters, shock conditions, ionization thresholds), use smooth approximations (e.g., `sigmoid` or `softplus`) to prevent zero or NaN gradients during automatic differentiation.

---

## 3. Julia Multiple Dispatch & Stiff ODEs

- Utilize `DifferentialEquations.jl` with native stiff solvers:
  - `Rodas5P` (5th-order A-stable Rosenbrock method for stiff systems).
  - `Vern9` (9th-order Verner method for ultra-high-precision celestial mechanics).
- Use `ForwardDiff.jl` for dual-number automatic differentiation of user-defined physical fluxes.
