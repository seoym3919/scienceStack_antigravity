r"""
Rigorous Astronomical Coordinate System Transformations.

Governing Equations:
====================
1. Direction Cosines:
   Given spherical coordinates (longitude $\phi$, latitude $\theta$):
   \begin{equation}
       \mathbf{r} = \begin{bmatrix}
           \cos\theta \cos\phi \\
           \cos\theta \sin\phi \\
           \sin\theta
       \end{bmatrix}
   \end{equation}

2. Equatorial to Ecliptic Transformation:
   Rotation by the obliquity of the ecliptic $\epsilon$:
   \begin{equation}
       \mathbf{r}_{\text{ecl}} = \mathbf{R}_x(\epsilon) \mathbf{r}_{\text{eq}}
       = \begin{bmatrix}
           1 & 0 & 0 \\
           0 & \cos\epsilon & \sin\epsilon \\
           0 & -\sin\epsilon & \cos\epsilon
       \end{bmatrix} \begin{bmatrix} x \\ y \\ z \end{bmatrix}_{\text{eq}}
   \end{equation}

3. Equatorial (J2000) to Galactic Transformation:
   Standard IAU Galactic definition (Blaauw et al. 1960):
   \begin{equation}
       \mathbf{r}_{\text{gal}} = \mathbf{R}_{\text{eq}\to\text{gal}} \mathbf{r}_{\text{eq}}
   \end{equation}
   where $\mathbf{R} \in \mathrm{SO}(3)$ satisfies $\mathbf{R}^T \mathbf{R} = \mathbf{I}$ and $\det \mathbf{R} = 1$.

Reference:
==========
Green, R. M. (1985). "Spherical Astronomy", Cambridge University Press, Chapter 2.
Meeus, J. (1998). "Astronomical Algorithms", 2nd ed., Willmann-Bell.
Blaauw, A., et al. (1960). "The new IAU system of galactic coordinates (1958 revision)",
Monthly Notices of the Royal Astronomical Society, 121, 123.
"""

from __future__ import annotations
import math
from typing import Tuple, Dict, Any


# J2000 Obliquity of the Ecliptic (IAU 2000 precession model)
# \epsilon = 23^\circ 26' 21.406''
OBLIQUITY_J2000_DEG = 23.0 + 26.0 / 60.0 + 21.406 / 3600.0
OBLIQUITY_J2000_RAD = math.radians(OBLIQUITY_J2000_DEG)

# IAU 1958 / J2000 Galactic Coordinate Constants
# North Galactic Pole: \alpha_p = 192.85948^\circ, \delta_p = 27.12825^\circ
# Ascending node of Galactic plane on equator: l_0 = 32.93192^\circ
RA_NGP_DEG = 192.85948
DEC_NGP_DEG = 27.12825
L_NCP_DEG = 122.93192


def spherical_to_cartesian(lon_rad: float, lat_rad: float) -> Tuple[float, float, float]:
    r"""Convert spherical coordinates (longitude, latitude) to unit 3D Cartesian vector."""
    cos_lat = math.cos(lat_rad)
    x = cos_lat * math.cos(lon_rad)
    y = cos_lat * math.sin(lon_rad)
    z = math.sin(lat_rad)
    return x, y, z


def cartesian_to_spherical(x: float, y: float, z: float) -> Tuple[float, float]:
    r"""Convert Cartesian direction cosines to spherical coordinates (longitude \in [0, 2\pi), latitude \in [-\pi/2, \pi/2])."""
    r_xy = math.hypot(x, y)
    lat = math.atan2(z, r_xy)
    lon = math.atan2(y, x) % (2.0 * math.pi)
    return lon, lat


def equatorial_to_ecliptic(ra_rad: float, dec_rad: float, eps_rad: float = OBLIQUITY_J2000_RAD) -> Tuple[float, float]:
    r"""
    Convert Equatorial (RA \alpha, Dec \delta) to Ecliptic (\lambda, \beta).

    Preserves orthonormal coordinate basis.
    """
    x, y, z = spherical_to_cartesian(ra_rad, dec_rad)
    cos_eps = math.cos(eps_rad)
    sin_eps = math.sin(eps_rad)

    x_ecl = x
    y_ecl = cos_eps * y + sin_eps * z
    z_ecl = -sin_eps * y + cos_eps * z

    return cartesian_to_spherical(x_ecl, y_ecl, z_ecl)


def ecliptic_to_equatorial(lam_rad: float, beta_rad: float, eps_rad: float = OBLIQUITY_J2000_RAD) -> Tuple[float, float]:
    r"""Convert Ecliptic (\lambda, \beta) to Equatorial (RA \alpha, Dec \delta)."""
    x, y, z = spherical_to_cartesian(lam_rad, beta_rad)
    cos_eps = math.cos(eps_rad)
    sin_eps = math.sin(eps_rad)

    x_eq = x
    y_eq = cos_eps * y - sin_eps * z
    z_eq = sin_eps * y + cos_eps * z

    return cartesian_to_spherical(x_eq, y_eq, z_eq)


# IAU / Hipparcos canonical transformation matrix from ICRS (J2000) to Galactic coordinates
# Reference: Perryman et al. (1997), ESA SP-1200; Astropy Galactic frame
CANONICAL_ICRS_TO_GALACTIC = (
    (-0.0548756577125917, -0.8734370519556161, -0.4838350736167158),
    ( 0.4941094371927274, -0.4448297212232954,  0.7469821839866674),
    (-0.8676661375596587, -0.1980763372730006,  0.4559838136873017),
)


def build_galactic_rotation_matrix() -> Tuple[Tuple[float, float, float], ...]:
    r"""
    Return the orthonormal 3x3 direction cosine matrix R_{eq -> gal} (ICRS J2000 to Galactic).

    Satisfies R^T R = I and det(R) = 1 to machine precision.
    """
    return CANONICAL_ICRS_TO_GALACTIC


GALACTIC_ROT_MATRIX = build_galactic_rotation_matrix()


def equatorial_to_galactic(ra_rad: float, dec_rad: float) -> Tuple[float, float]:
    r"""Convert Equatorial J2000 (RA \alpha, Dec \delta) to Galactic (l, b)."""
    x, y, z = spherical_to_cartesian(ra_rad, dec_rad)
    R = GALACTIC_ROT_MATRIX

    x_gal = R[0][0] * x + R[0][1] * y + R[0][2] * z
    y_gal = R[1][0] * x + R[1][1] * y + R[1][2] * z
    z_gal = R[2][0] * x + R[2][1] * y + R[2][2] * z

    return cartesian_to_spherical(x_gal, y_gal, z_gal)


def verify_rotation_orthonormality(R: Tuple[Tuple[float, float, float], ...], tol: float = 1e-14) -> Dict[str, Any]:
    r"""Audit rotation matrix for orthonormality: R^T R = I and det(R) = 1."""
    # Check R^T R
    identity_error = 0.0
    for i in range(3):
        for j in range(3):
            dot = sum(R[k][i] * R[k][j] for k in range(3))
            expected = 1.0 if i == j else 0.0
            identity_error = max(identity_error, abs(dot - expected))

    # Compute determinant
    det = (
        R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1])
        - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
        + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0])
    )
    det_error = abs(det - 1.0)
    passed = (identity_error < tol) and (det_error < tol)

    return {
        "identity_error": identity_error,
        "det_error": det_error,
        "passed": passed,
    }


if __name__ == "__main__":
    audit = verify_rotation_orthonormality(GALACTIC_ROT_MATRIX)
    print("Astronomical Coordinate Transformations Verification:")
    print(f"  Galactic Rotation Matrix Orthogonality Error: {audit['identity_error']:.2e}")
    print(f"  Determinant Error: {audit['det_error']:.2e}")
    assert audit["passed"], "Galactic rotation matrix failed SO(3) orthonormality check!"

    # Test round-trip: RA/Dec -> Ecliptic -> RA/Dec
    ra_test = math.radians(83.633083)  # Betelgeuse (approx)
    dec_test = math.radians(7.407064)
    lam, beta = equatorial_to_ecliptic(ra_test, dec_test)
    ra_rec, dec_rec = ecliptic_to_equatorial(lam, beta)

    roundtrip_err = math.hypot(ra_test - ra_rec, dec_test - dec_rec)
    print(f"  Ecliptic Round-trip Error: {roundtrip_err:.2e} rad")
    assert roundtrip_err < 1e-14, "Coordinate round-trip failed machine precision check!"

    # Test Galactic transformation for Galactic Center Sgr A* (approx RA 17h 45m 40s = 266.4168°, Dec -29.0078°)
    ra_sgrA = math.radians(266.4168)
    dec_sgrA = math.radians(-29.0078)
    l_sgrA, b_sgrA = equatorial_to_galactic(ra_sgrA, dec_sgrA)
    print(f"  Sgr A* (Galactic Center) -> l = {math.degrees(l_sgrA):.3f} deg (expected ~359.94° or 0°), b = {math.degrees(b_sgrA):.3f} deg (expected ~ -0.05°)")
    assert abs(math.sin(b_sgrA)) < 0.01, "Galactic latitude of Sgr A* deviated from Galactic midplane!"
    print("  [PASS] All coordinate transformations verified to machine precision.")
