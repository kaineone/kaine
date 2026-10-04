# Individuation instrument offline validation report

- seed: 20261003
- git commit: 8cbf926
- sigma: 1.0
- quick mode: False
- mean within-prompt cosine (baseline): 0.2357

## 1. Size (type-I error)

N=5000, n_b=16, n_c=8, permutations=999.

| alpha | rate | 2SE bound | pass |
|-------|------|-----------|------|
| 0.05 | 0.0446 | 0.0562 | PASS |
| 0.01 | 0.0078 | 0.0128 | PASS |

KS uniformity: worst t=0.56, value=0.0106, bound=0.0173 -> PASS.

## 2. Lifetime (familywise error under H0)

L=2000, looks=100, mean permutations/look=4145.

| look | instrument | naive | old_percentile |
|------|------------|-------|----------------|
| 10 | 0.035 (±0.008) | 0.334 (±0.021) | 0.503 (±0.022) |
| 50 | 0.037 (±0.008) | 0.777 (±0.019) | 0.970 (±0.008) |
| 100 | 0.038 (±0.009) | 0.903 (±0.013) | 1.000 (±0.001) |

Instrument look-100 bound=0.0597 -> PASS.

## 3. Power

R=200, sigma=1.0.

| condition | look | power | ±2SE |
|-----------|------|-------|------|
| 12x6_cluster-pi0.25 | 1 | 0.455 | 0.070 |
| 12x6_cluster-pi0.25 | 10 | 0.065 | 0.035 |
| 12x6_cluster-pi0.5 | 1 | 0.995 | 0.010 |
| 12x6_cluster-pi0.5 | 10 | 0.960 | 0.028 |
| 12x6_partial-m3-pi0.5 | 1 | 0.415 | 0.070 |
| 12x6_partial-m3-pi0.5 | 10 | 0.040 | 0.028 |
| 12x6_partial-m6-pi0.5 | 1 | 0.855 | 0.050 |
| 12x6_partial-m6-pi0.5 | 10 | 0.405 | 0.069 |
| 12x6_shift-d0.25 | 1 | 0.190 | 0.055 |
| 12x6_shift-d0.25 | 10 | 0.015 | 0.017 |
| 12x6_shift-d0.5 | 1 | 1.000 | 0.000 |
| 12x6_shift-d0.5 | 10 | 0.605 | 0.069 |
| 16x8_cluster-pi0.25 | 1 | 0.675 | 0.066 |
| 16x8_cluster-pi0.25 | 10 | 0.160 | 0.052 |
| 16x8_cluster-pi0.5 | 1 | 1.000 | 0.000 |
| 16x8_cluster-pi0.5 | 10 | 0.990 | 0.014 |
| 16x8_cluster-pi0.5 | 50 | 0.985 | 0.017 |
| 16x8_partial-m3-pi0.5 | 1 | 0.620 | 0.069 |
| 16x8_partial-m3-pi0.5 | 10 | 0.135 | 0.048 |
| 16x8_partial-m6-pi0.5 | 1 | 0.960 | 0.028 |
| 16x8_partial-m6-pi0.5 | 10 | 0.635 | 0.068 |
| 16x8_partial-m6-pi0.5 | 50 | 0.425 | 0.070 |
| 16x8_shift-d0.25 | 1 | 0.310 | 0.065 |
| 16x8_shift-d0.25 | 10 | 0.010 | 0.014 |
| 16x8_shift-d0.5 | 1 | 1.000 | 0.000 |
| 16x8_shift-d0.5 | 10 | 0.995 | 0.010 |
| 24x12_cluster-pi0.25 | 1 | 0.905 | 0.041 |
| 24x12_cluster-pi0.25 | 10 | 0.455 | 0.070 |
| 24x12_cluster-pi0.5 | 1 | 1.000 | 0.000 |
| 24x12_cluster-pi0.5 | 10 | 1.000 | 0.000 |
| 24x12_partial-m3-pi0.5 | 1 | 0.910 | 0.040 |
| 24x12_partial-m3-pi0.5 | 10 | 0.365 | 0.068 |
| 24x12_partial-m6-pi0.5 | 1 | 1.000 | 0.000 |
| 24x12_partial-m6-pi0.5 | 10 | 0.975 | 0.022 |
| 24x12_shift-d0.25 | 1 | 0.695 | 0.065 |
| 24x12_shift-d0.25 | 10 | 0.045 | 0.029 |
| 24x12_shift-d0.5 | 1 | 1.000 | 0.000 |
| 24x12_shift-d0.5 | 10 | 1.000 | 0.000 |

Pre-registered acceptance (look=10, 16x8, cluster-pi0.5): power=0.990, threshold=0.8 -> PASS.

## 4. Energy vs. MMD (16x8 only)

R=100.

| condition | look | energy | mmd |
|-----------|------|--------|-----|
| cluster-pi0.25 | 1 | 0.680 | 0.640 |
| cluster-pi0.25 | 10 | 0.210 | 0.220 |
| cluster-pi0.5 | 1 | 1.000 | 1.000 |
| cluster-pi0.5 | 10 | 1.000 | 1.000 |
| partial-m3-pi0.5 | 1 | 0.570 | 0.530 |
| partial-m3-pi0.5 | 10 | 0.170 | 0.140 |
| partial-m6-pi0.5 | 1 | 0.950 | 0.950 |
| partial-m6-pi0.5 | 10 | 0.740 | 0.690 |
| shift-d0.25 | 1 | 0.370 | 0.370 |
| shift-d0.25 | 10 | 0.010 | 0.020 |
| shift-d0.5 | 1 | 1.000 | 1.000 |
| shift-d0.5 | 10 | 1.000 | 1.000 |
