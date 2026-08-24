# Queue-Depth + Latency Operational Envelope

Calm vs storm queue-depth + S2S-latency envelope across SDK poller count and matching partitions (write=read). Pre-registration 0e61dde262a8eaf67926f0f366b48433da39039fad5f71260f955d2f8f968dee. Per-cell medians across valid runs.

| cell | workload | pollers | parts | runs | max depth | final depth | history | p50 | p90 | p99 | max | mean | fail | aps | config hash |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| storm_p2_r1 | storm | 2 | 1 | 3 | 12 | 12 | 0 | 512.0 | 512.0 | 512.0 | 512.0 | 397.7 | 0.000 | 7.12 | 4ea2a2af18e1bd966afbfb64b1162c47d26448931211a12f959823b963b7057e |
| storm_p2_r4 | storm | 2 | 4 | 3 | 6 | 1 | 0 | 512.0 | 512.0 | 1024.0 | 2048.0 | 472.9 | 0.000 | 6.02 | c4ab9323996b7139f2ab49771e456c844b7bff5bb3b97e0b9df3b3bc89d73121 |
| storm_p10_r1 | storm | 10 | 1 | 3 | 4 | 4 | 0 | 512.0 | 512.0 | 512.0 | 512.0 | 399.2 | 0.000 | 7.02 | 3ea09e04c6ffed47927bcd2ae8bf691b9c5c413d9f34d608e7ca7886b3c56bb1 |
| storm_p10_r4 | storm | 10 | 4 | 3 | 0 | 0 | 0 | 512.0 | 512.0 | 512.0 | 512.0 | 400.7 | 0.000 | 4.74 | 85c64b8bbcbb3af8113420599b66b9312879b84889418d05e19a31136c794872 |
| storm_p30_r1 | storm | 30 | 1 | 3 | 0 | 0 | 0 | 64.0 | 512.0 | 512.0 | 512.0 | 388.5 | 0.000 | 7.12 | ab994e3a083274cc981bfc2c9e1bb4671d1ee4f45951951adee9669ab533264a |
| storm_p30_r4 | storm | 30 | 4 | 3 | 0 | 0 | 0 | 512.0 | 512.0 | 512.0 | 512.0 | 396.6 | 0.000 | 2.84 | a1e2323bed71307965b16b5ad14a4a6e05259c811ef4aff68644d5ab30b31be2 |
| calm_p10_r1 | calm | 10 | 1 | 3 | 0 | 0 | 0 | 2.0 | 32.0 | 32.0 | 64.0 | 15.8 | 0.000 | 2.00 | d66f36437a58ac76d08ef625dbe1a5e02d867b35fce879a6e8db37dbc536bdb6 |
| calm_p10_r4 | calm | 10 | 4 | 3 | 0 | 0 | 0 | 4.0 | 32.0 | 64.0 | 64.0 | 17.9 | 0.000 | 1.32 | 4c2391f6fb47ffd7a4b0ba3e2bc49e74bff459ba13b5bcdb2b7f5664cddabf6a |

Env: go go1.27.0, commit ba50f4054c6e79129cf11c75b254649afa98fdc9, host omarchy, pre-registration 0e61dde262a8eaf67926f0f366b48433da39039fad5f71260f955d2f8f968dee.
