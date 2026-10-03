### published

| method | n_parts | evaluable_share | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|---|
| static_limits | 9779 | 1.000 | 21 | 0.002 | 0.040 | 1.000 | 0 | 500 | 0.511 |
| fixed_delta | 9779 | 1.000 | 2344 | 0.240 | 1.000 | 0.222 | 1823 | 0 | 0.186 |
| static_pat | 9779 | 1.000 | 666 | 0.068 | 0.447 | 0.350 | 433 | 288 | 0.339 |
| dynamic_pat | 9779 | 1.000 | 317 | 0.032 | 0.591 | 0.972 | 9 | 213 | 0.219 |
| module_a_review | 9779 | 1.000 | 2378 | 0.243 | 0.841 | 0.184 | 1940 | 83 | 0.283 |
| module_a_reject | 9779 | 1.000 | 1998 | 0.204 | 0.787 | 0.205 | 1588 | 111 | 0.276 |

### live

| method | n_parts | evaluable_share | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|---|
| static_limits | 9779 | 1.000 | 21 | 0.002 | 0.040 | 1.000 | 0 | 500 | 0.511 |
| fixed_delta | 9779 | 1.000 | 2344 | 0.240 | 1.000 | 0.222 | 1823 | 0 | 0.186 |
| static_pat | 9779 | 1.000 | 666 | 0.068 | 0.447 | 0.350 | 433 | 288 | 0.339 |
| dynamic_pat | 9779 | 1.000 | 317 | 0.032 | 0.591 | 0.972 | 9 | 213 | 0.219 |
| module_a_review | 9779 | 1.000 | 1787 | 0.183 | 0.814 | 0.237 | 1363 | 97 | 0.239 |
| module_a_reject | 9779 | 1.000 | 1505 | 0.154 | 0.758 | 0.262 | 1110 | 126 | 0.242 |

### hist2

| method | n_parts | evaluable_share | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|---|
| static_limits | 9779 | 1.000 | 21 | 0.002 | 0.040 | 1.000 | 0 | 500 | 0.511 |
| fixed_delta | 9779 | 1.000 | 2344 | 0.240 | 1.000 | 0.222 | 1823 | 0 | 0.186 |
| static_pat | 9779 | 1.000 | 666 | 0.068 | 0.447 | 0.350 | 433 | 288 | 0.339 |
| dynamic_pat | 9779 | 1.000 | 317 | 0.032 | 0.591 | 0.972 | 9 | 213 | 0.219 |
| module_a_review | 9779 | 1.000 | 2234 | 0.228 | 0.839 | 0.196 | 1797 | 84 | 0.270 |
| module_a_reject | 9779 | 1.000 | 1862 | 0.190 | 0.777 | 0.218 | 1457 | 116 | 0.268 |

### hist5

| method | n_parts | evaluable_share | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|---|
| static_limits | 9779 | 1.000 | 21 | 0.002 | 0.040 | 1.000 | 0 | 500 | 0.511 |
| fixed_delta | 9779 | 1.000 | 2344 | 0.240 | 1.000 | 0.222 | 1823 | 0 | 0.186 |
| static_pat | 9779 | 1.000 | 666 | 0.068 | 0.447 | 0.350 | 433 | 288 | 0.339 |
| dynamic_pat | 9779 | 1.000 | 317 | 0.032 | 0.591 | 0.972 | 9 | 213 | 0.219 |
| module_a_review | 9779 | 1.000 | 2382 | 0.244 | 0.837 | 0.183 | 1946 | 85 | 0.286 |
| module_a_reject | 9779 | 1.000 | 1998 | 0.204 | 0.775 | 0.202 | 1594 | 117 | 0.283 |

### hist10

| method | n_parts | evaluable_share | n_flagged | flag_rate | recall | precision | false_alarms | missed | cost_per_part |
|---|---|---|---|---|---|---|---|---|---|
| static_limits | 9779 | 1.000 | 21 | 0.002 | 0.040 | 1.000 | 0 | 500 | 0.511 |
| fixed_delta | 9779 | 1.000 | 2344 | 0.240 | 1.000 | 0.222 | 1823 | 0 | 0.186 |
| static_pat | 9779 | 1.000 | 666 | 0.068 | 0.447 | 0.350 | 433 | 288 | 0.339 |
| dynamic_pat | 9779 | 1.000 | 317 | 0.032 | 0.591 | 0.972 | 9 | 213 | 0.219 |
| module_a_review | 9779 | 1.000 | 2405 | 0.246 | 0.841 | 0.182 | 1967 | 83 | 0.286 |
| module_a_reject | 9779 | 1.000 | 1991 | 0.204 | 0.779 | 0.204 | 1585 | 115 | 0.280 |

### cost per part, published minus live

| family | method | n_parts | cost_published | cost_live | cost_published_minus_live | ci_lo | ci_hi | recall_published | recall_live | flag_rate_published | flag_rate_live |
|---|---|---|---|---|---|---|---|---|---|---|---|
| altered_correlation | module_a_review | 1848 | 0.242 | 0.198 | 0.044 | 0.010 | 0.073 | 0.879 | 0.849 | 0.225 | 0.162 |
| altered_correlation | module_a_reject | 1848 | 0.235 | 0.213 | 0.023 | -0.019 | 0.052 | 0.818 | 0.778 | 0.182 | 0.135 |
| baseline | module_a_review | 2541 | 0.252 | 0.192 | 0.059 | 0.046 | 0.072 | 0.885 | 0.885 | 0.240 | 0.181 |
| baseline | module_a_reject | 2541 | 0.221 | 0.173 | 0.048 | 0.036 | 0.060 | 0.865 | 0.865 | 0.201 | 0.153 |
| different_noise_regime | module_a_review | 2310 | 0.262 | 0.209 | 0.052 | 0.026 | 0.074 | 0.899 | 0.869 | 0.257 | 0.191 |
| different_noise_regime | module_a_reject | 2310 | 0.255 | 0.213 | 0.042 | 0.013 | 0.067 | 0.838 | 0.798 | 0.222 | 0.161 |
| higher_defect_prevalence | module_a_review | 924 | 0.568 | 0.596 | -0.028 | -0.100 | 0.036 | 0.686 | 0.628 | 0.247 | 0.192 |
| higher_defect_prevalence | module_a_reject | 924 | 0.651 | 0.664 | -0.013 | -0.062 | 0.034 | 0.603 | 0.562 | 0.211 | 0.165 |
| wider_drift_exponent | module_a_review | 2156 | 0.257 | 0.205 | 0.051 | 0.033 | 0.068 | 0.888 | 0.878 | 0.246 | 0.190 |
| wider_drift_exponent | module_a_reject | 2156 | 0.237 | 0.199 | 0.038 | 0.018 | 0.055 | 0.847 | 0.827 | 0.206 | 0.158 |
| ALL | module_a_review | 9779 | 0.283 | 0.239 | 0.045 | 0.032 | 0.057 | 0.841 | 0.814 | 0.243 | 0.183 |
| ALL | module_a_reject | 9779 | 0.276 | 0.242 | 0.034 | 0.021 | 0.045 | 0.787 | 0.758 | 0.204 | 0.154 |

### M3 decision

{'cost_published_minus_live': {'module_a_review': 0.04468759586869823, 'module_a_reject': 0.03354126188771858}, 'threshold': 0.01, 'verdict': 'the Isolation Forest matters'}
