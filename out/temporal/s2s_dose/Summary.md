# S2S Dose Bubble Sweep

Bubble leg of the dose-response frontier (plan 2026-08-13, pre-registration hash 941d557d0b50b6a31842a70b6619f57d8bfa6afc06c06811ada013a778399406). Per-dose: median/min/max fail fraction across valid runs; throughput from trace.jsonl over the storm window [1000, 10001).

| dose | runs | fail med (min..max) | aps | horizon | poll/s | add/s | act-share | config hash |
|---|---|---|---|---|---|---|---|---|
| 100 | 3 | 1.000 (1.000..1.000) | 2.10 | 1790ms | 6 | 0 | 0.473 | 579f3fa4bdab23f2ef9699e171981c2d96a89f1ea275025732b58a6fb529374e |
| 125 | 3 | 1.000 (1.000..1.000) | 2.06 | 1770ms | 6 | 0 | 0.473 | 7dade4121a878363e0d1ed5e33dc8dce4c5f24200294310b7ff0dfd46677d1dd |
| 150 | 3 | 1.000 (1.000..1.000) | 2.04 | 1781ms | 6 | 0 | 0.485 | 0281ae39406122dc62eec1a2a87b1b32ca75a5c49b79d656f47054de837b4185 |
| 200 | 3 | 1.000 (1.000..1.000) | 2.08 | 1783ms | 6 | 0 | 0.482 | 9a83d9af6c2f5ef3ad3f6d57c3f04feaa9ce4620b79164af7591ebae40c755ef |
| 300 | 3 | 1.000 (1.000..1.000) | 2.06 | 1741ms | 6 | 0 | 0.468 | 3a8f956d9c9f3a3d0103ce30953be549a1d89f370c9bd7439d86a0cb437ba27f |
| 400 | 5 | 1.000 (1.000..1.000) | 2.12 | 3693ms | 6 | 1 | 0.480 | 954536c7ccefdc5f09a5b87376a7caaa8b2194f5197ccf3e022ad5e72dd3ea97 |
| 500 | 5 | 1.000 (1.000..1.000) | 2.10 | 1778ms | 6 | 0 | 0.478 | 78b0b1db389a19ae2284d534ef6ca72a6d1c1727d71907cb348656774da6c2d9 |
| 700 | 5 | 1.000 (1.000..1.000) | 2.10 | 1764ms | 6 | 0 | 0.464 | 995bff1965b07984569ebe7ed7d1b6f6ef8cc58e55aaaf3ecfd35626ec2a1b82 |
| 1000 | 5 | 0.540 (0.420..0.660) | 9.36 | 10621ms | 41 | 39 | 0.885 | 5aac8d4f61c56631244cda215d36d7cf975f09fd3e4d8953d68a26173652a870 |
| 1500 | 3 | 0.000 (0.000..0.000) | 10.58 | 10818ms | 50 | 43 | 0.899 | 12104ed5ba2d4bf4766932f917c91dc5cd807a639ed6b48f2091499533bca9c8 |
| 2000 | 3 | 0.000 (0.000..0.000) | 10.92 | 10798ms | 51 | 43 | 0.900 | d3f0e0c8554d3dca431d9a7824fa518891c29f38361748a4b0b7b1e3f4165300 |
| calm | 3 | 0.000 | 2.08 | 1074ms | 1 | 1 | 0.484 | 9468c08e19ff902aad4c3646aecc4112ffc5e685080bb10d7d67012639d561aa |

Env: go go1.27.0, commit ba50f4054c6e79129cf11c75b254649afa98fdc9, host omarchy, pre-registration 941d557d0b50b6a31842a70b6619f57d8bfa6afc06c06811ada013a778399406.
