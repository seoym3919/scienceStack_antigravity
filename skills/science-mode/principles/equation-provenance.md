---
name: principle-equation-provenance
description: "Every formula or equation in code must cite its textbook/paper source, state the LaTeX equation in docstrings, list variable units, and document coordinate systems and sign conventions. Use when implementing, refactoring, or auditing equations."
disable-model-invocation: true
---

# Principle: Equation Provenance

Never write a non-trivial mathematical formula, physical law, or algorithm as bare, unannotated code.

Code implementing scientific theory is unreviewable and untrustworthy unless the path from the theoretical equation to the code is explicit, cited, and traceable.

## When it applies

- Writing or reviewing any function implementing a mathematical formula, physical model, loss function, or discrete operator.
- Refactoring algorithms where variables have mathematical interpretations.
- Porting formulas from papers, textbooks, or reference implementations.

## Rules

1. **State the Governing Equation in LaTeX**:
   In the docstring of the function or class, write the exact continuous or discrete equation in standard LaTeX notation:
   ```python
   def lennard_jones_potential(r: float, epsilon: float, sigma: float) -> float:
       r"""
       Computes the 12-6 Lennard-Jones interatomic potential:
       
       .. math::
           V(r) = 4 \varepsilon \left[ \left(\frac{\sigma}{r}\right)^{12} - \left(\frac{\sigma}{r}\right)^6 \right]

       Parameters
       ----------
       r : float
           Interatomic distance [m or \AA]. Must be > 0.
       epsilon : float
           Depth of the potential well \varepsilon [J or eV].
       sigma : float
           Distance at which the potential is zero \sigma [m or \AA].

       Returns
       -------
       float
           Potential energy V(r) [J or eV].
       """
   ```

2. **Cite the Provenance**:
   Include the exact source:
   - Paper: Authors, Title, Journal/ArXiv, Year, Equation number (e.g., `Eq. (14) in Smith et al., Phys. Rev. B 2023`).
   - Textbook: Title, Author, Edition, Page/Chapter/Equation number.
   - Specification / Standard: Document name, Section, Equation number.

3. **Explicit Coordinate Systems & Conventions**:
   State coordinate conventions without ambiguity:
   - Right-handed vs. left-handed coordinate frame.
   - Index ordering for multidimensional arrays (e.g., `(batch, channel, z, y, x)` vs `(x, y, z)`).
   - Sign conventions (e.g., metric signature $(-, +, +, +)$ vs $(+, -, -, -)$; Fourier transform sign $e^{-i \omega t}$ vs $e^{+i \omega t}$).
   - Normalization constants (e.g., unitary Fourier transform with $1/\sqrt{2\pi}$ vs non-unitary with $1$).

4. **Map Variable Names to Math Symbols**:
   Every code variable must be explicitly linked to its mathematical counterpart in the docstring table (e.g. `gamma_dot: shear rate \dot{\gamma}`). Never invent vague abbreviations for well-established mathematical symbols.

5. **Document Assumptions and Domain of Validity**:
   State mathematical and physical domain requirements:
   - Positivity: $r > 0$, $T \ge 0$, $\rho > 0$.
   - Singularity handling: behavior as $x \to 0$ or $x \to \infty$.
   - Dimensionless groups: Reynolds number range $Re \ll 1$ (Stokes flow) vs turbulent.
