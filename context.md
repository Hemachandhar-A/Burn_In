# Context & Decision Record — SIH 26170: AI-Driven Anomaly Detection in Component Burn-In & Screening

**This is the root document.** It is written to be fully self-contained: a reader (human or AI coding agent) with zero prior exposure to this project should be able to understand the problem, the reasoning behind every major decision, and the complete system design from this file alone.

## How these five documents relate

| Document | Purpose | Read this for |
|---|---|---|
| **`context.md`** (this file) | The root reference | The problem itself, all background research, every "why we chose this" rationale, and the complete locked app flow |
| **`essential-features.md`** | The must-build spec | What each essential feature is, how to implement it, practicality — short rationale only, links back here for the full evidence |
| **`non-essential-features.md`** | The stretch-goal spec | Same shape as above, for features to build only if time remains |
| **`IMPLEMENTATION_PLAN.md`** | The build sequence | Who builds what, in what order, against what frozen data contract, and how it gets tested and merged |
| **`AGENTS.md`** | The per-session rulebook | The short, operational ruleset each person's coding-agent session reads before touching code |

The split exists so the team can edit the feature docs freely as implementation details change, without touching the slower-moving reasoning in this file.

---

# Part 1 — The Problem, From Zero

## 1.1 Who is asking, and what for

This is Smart India Hackathon (SIH) Problem Statement **26170**, titled *"AI-Driven Anomaly Detection in Component Burn-In & Screening,"* posed by ISRO, in the Software category. The organizers provided **no dataset** — the problem statement explicitly says so. That single fact shapes almost every downstream decision in this project (see Part 3).

## 1.2 Why electronic components get "burned in" at all

Components destined for spacecraft cannot be repaired once launched. To reduce the risk of a part failing in orbit, high-reliability manufacturers subject components to **Environmental Stress Screening (ESS)**, of which **burn-in testing** is the classic method: operating a part at an elevated temperature (commonly 125°C) for an extended period before it is accepted for use.

The official purpose of burn-in, per the governing military standard, is to eliminate **marginal devices** — parts with inherent manufacturing defects that would otherwise surface later as **infant mortality** or early-life field failures. This comes directly from [MIL-STD-883 Method 1015, as quoted by the FDA's own inspection guidance](https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/inspection-guides/screening-electronic-components): burn-in is performed "for the purpose of eliminating marginal devices, those with inherent defects or defects resulting from manufacturing aberrations which are evidenced as time and stress dependent failures." MIL-STD-883 is the governing U.S. military test-method standard for microelectronics used in military and aerospace systems, and Method 1015 (burn-in) is one of dozens of test methods it defines — [see the standard's structure](https://en.wikipedia.org/wiki/MIL-STD-883).

Real screening flows specify exact durations by quality class. One widely cited table of [MIL-STD-883 Method 5004 screening requirements](https://eesemi.com/milscreens.htm) lists burn-in at "1015, 240H at 125C min." for Class-S (the highest space-grade class) and "1015, 160H at 125C min." for Class-B. Your problem statement's checkpoints (0h, 24h, 96h, 168h) sit inside this normal range — 168h (7 days) is a plausible full-duration read point.

## 1.3 What actually gets measured

At each checkpoint, the lab measures **parametric** values — small electrical numbers, not pass/fail functional tests:

- **Iddq** (quiescent supply current): the current a CMOS chip draws while sitting idle (not switching). In a defect-free chip this should be tiny. Per a [semiconductor testing patent](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6489800), Iddq is "basically the sum of the so-called sub-threshold currents of the MOS transistors... and of the leakage currents due to manufacturing defects or material defects." In other words, **Iddq = background subthreshold leakage + defect current**. As process nodes have shrunk, background leakage has grown to the point that, per an [EDN industry article](https://www.edn.com/?p=4041004), "the magnitude of the background current is comparable to or even exceeds many defect currents" — meaning a raw Iddq threshold alone struggles to separate "leaky but healthy" from "leaky because defective." This single fact is the technical justification for the whole problem statement: **you cannot screen on Iddq using a fixed number alone.**
- **Leakage current**: unintended current flow through the device. Depending on context this can mean the same subthreshold leakage inside Iddq, or a separately specified I/O pin leakage (reverse-biased junction leakage at a high-impedance pin), which one [semiconductor test patent notes](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6489800) is "at least two orders of magnitude lower" than subthreshold current and "thus negligible" as a fraction of Iddq. Practically: Iddq and leakage current are **related but not identical measurements** — a defect can plausibly raise both (shared root cause) without them being redundant duplicates of one number. A real Iddq patent example gives [good-die Iddq typically ranging 5–35 µA across different lots](https://patents.google.com/patent/US6681193) of the same device — i.e., lot-to-lot variation of several times is normal even among healthy parts, which is exactly why a single global threshold is weak.
- **Propagation delay**: how long it takes a signal to pass through logic. It typically slows down (increases) as a device degrades — see 1.4 below.

**Why these three, and not others.** Worth being direct about the actual reasoning rather than reconstructing a tidier one after the fact. The primary driver is that the problem statement names exactly these three as its own examples — matching that language means every downstream citation traces back to what's actually being judged. The secondary, genuinely technical reason: these three span the two main channels a latent defect shows up in — Iddq/leakage cover the *current* channel, propagation delay covers the *timing* channel, a different physical mechanism (Vt shift via NBTI, 1.4) rather than leakage. **What this is not:** a formal feature-selection study — no mutual-information or defect-detectability comparison was run across a wider candidate pool to prove these three are optimal. That is a scope decision, disclosed as one (Part 8.1), not a data-driven result.

## 1.4 Why parts drift over time — the physics behind Module B

The dominant aging mechanism behind slow parametric drift in modern CMOS is **Negative-Bias Temperature Instability (NBTI)**: positive charge traps at the gate-oxide interface over time, raising the transistor's threshold voltage and therefore slowing switching speed and altering leakage. [Wikipedia's summary of NBTI](https://en.wikipedia.org/wiki/Negative-bias_temperature_instability) states plainly that "the degradation is often approximated by a power-law dependence on time" — i.e., ΔV(t) ∝ tⁿ, not a straight line.

The exponent **n is not fixed** — real measurement studies show a spread. A study from Liverpool John Moores University plots real fitted time exponents clustering in the **n ≈ 0.15–0.30** range across several process technologies ([see Figure 1a of the paper](https://researchonline.ljmu.ac.uk/id/eprint/6810/1/FINAL%20VERSION.pdf)), and a 2026 arXiv paper on NBTI mitigation states a commonly used value of **n ≈ 0.25** ([OptGM paper, Section on NBTI factors](https://arxiv.org/pdf/2506.21487)). This sub-linear ("quasi-saturating") shape matters enormously for Module B: naively extrapolating a straight line from a 0h→24h reading to 168h would **overshoot** a healthy part's real drift by roughly 4–5×, because true drift grows more slowly than time.

Temperature-driven acceleration of failure mechanisms (not just NBTI, but defect activation generally) is classically modeled by the **Arrhenius equation**, linking a failure mechanism's rate to an activation energy Eₐ and absolute temperature. [JEDEC Publication JEP122](https://moodle1.u-bordeaux.fr/pluginfile.php/971683/mod_resource/content/1/1_3qualif.pdf) is the standard reference for this in microelectronics reliability qualification. Activation energies for electronics-related mechanisms are documented across a wide range, roughly **0.3–2.0 eV** depending on mechanism ([reference](https://beowulf.org/pipermail/beowulf/2005-March/012172.html); mechanism-specific breakdowns in [3.3](#33-the-generators-physical-grounding)) — genuinely uncertain without device-specific characterization, which is exactly why we treat it as a randomized parameter in the synthetic generator (Part 3) rather than a fixed constant.

## 1.5 Why some defective parts still pass — "latent defects" and infant mortality

The bathtub-curve model of reliability engineering describes an early-life period with a **declining** hazard rate, caused by discrete manufacturing defects that only produce failures once activated by operating stress — as opposed to the constant-rate "useful life" period or the rising "wear-out" period ([IEEE Reliability description of early life](https://technav.ieee.org/topic/early-life/)). The **Weibull distribution** with a shape parameter below 1 is the standard statistical model for this declining-hazard early-life behavior.

The critical insight the problem statement is built around: a part can sit **under** every datasheet absolute-maximum limit at every checkpoint, and still be on a trajectory that marks it as one of these early-life-risk parts. A fixed pass/fail threshold, by definition, cannot see this — it only asks "did you cross the line," not "are you moving toward the line faster than your peers."

## 1.6 What industry already does about this — the closest existing answer

This is not a problem industry has ignored. The **Automotive Electronics Council's AEC-Q001** specification defines **Part Average Testing (PAT)**, described plainly in an [EDN industry article](https://www.edn.com/?p=4011021): PAT "prescribes finding test results that fall outside six sigma from the population mean for a given wafer, lot, or group of parts being tested" — explicitly to catch parts that pass absolute limits but stand out from their peer population.

The exact formulas, per a [PAT-implementation patent](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11919046) and a [yieldWerx technical explainer](https://yieldwerx.com/blog/ultimate-guide-to-outlier-detection-using-part-average-testing/):
- **Robust mean** = the median of the sorted data.
- **Robust sigma** = (75th-percentile value − 25th-percentile value) ÷ 1.35 (i.e., IQR/1.35).
- **Static PAT limits** = Robust Mean ± 6 × Robust Sigma, computed from a large pooled reference population and updated periodically.
- **Dynamic PAT (DPAT)** recomputes these limits **per lot**, in real time, rather than using a fixed pooled reference — directly matching the problem statement's request for a "dynamic" system. A [Keysight case study](https://www.keysight.com/be/en/assets/3121-1257/case-studies/Moving-from-Static-Limits-to-Dynamic-Part-Average-Test-PAT-Limits.pdf) on implementing pseudo-real-time DPAT in a real production line reports a measured reduction of "greater than 2%" in total false rejects versus static per-lot limits.

Notably, National Instruments' own semiconductor test platform documents PAT as a defined concept but states explicitly that "[TSM] does not install a default implementation of part average testing" ([NI TestStand documentation](https://www.ni.com/docs/en-US/bundle/teststand-semiconductor-module/page/part-average-testing.html)) — the method is left to the user to build. **This is a real, disclosed gap our system fills.**

**What PAT/DPAT does not do:** it is a per-checkpoint snapshot comparison. It does not forecast a future reading from early data, and it is not designed around a fixed burn-in campaign's time-series structure. That gap is exactly what your problem statement's Module B (drift prediction) is asking for, and it is why our system does not simply reimplement DPAT — it uses DPAT-style statistics as one input among several (Part 4, Part 7).

## 1.7 Lot-level acceptance — the industry's other half of this problem

Beyond individual parts, real screening flows also make a **lot-level** accept/reject decision using a **Percent Defective Allowable (PDA)**. Real component datasheets state this explicitly — for example, a [radiation-hardened voltage regulator datasheet](https://html.alldatasheet.net/html-pdf/257525/LINER/RH1085/459/3/RH1085.html): "The PDA is specified as 5% based on failures from group A, subgroup 1, tests after cooldown in accordance with method 5004 of MIL-STD-883 Class B." A [NASA NEPP workshop slide deck comparing MIL-STD-883 and AEC-Q100](https://nepp.nasa.gov/workshops/etw2020/talks/15-JUN-MON/1630-Lilani-Yarbrough-Harzstark-Cozzolino-NEPP-ETW-AEC_pt2.pdf) shows PDA values ranging from 5% total (3% functional) down to 1% depending on quality grade. A separate [Analog Devices space-grade part specification](https://docs.ampnuts.ru/analog.com.datasheet/rt6804-1/related_data/05-08-5753.pdf) confirms that "delta limit parameters... are calculated after each burn-in, and the delta rejects are included in the PDA calculation" — i.e., **delta (drift) failures feed directly into the same lot-disposition math as absolute failures.** This is the direct real-world precedent for our system's lot-level rollup (Part 7, Stage 5).

## 1.8 The three things the problem statement is actually judging

1. **Anomaly Detection Score** — explicitly penalizes **false negatives** (a defective part let through) far more than false positives. This is a cost-asymmetric scoring rule, not a plain accuracy metric.
2. **Drift Prediction Accuracy** — mean absolute error between predicted and actual (hidden) Value_168h.
3. **Explainability** — can the system justify its classification to a **QA inspector**, in terms a human reviewer would accept, or is it an opaque black box.

Everything in this project is designed against these three criteria specifically, not against generic ML benchmarks.

---

# Part 2 — Landscape: What Already Exists

We searched three separate categories, because "no dataset given" does not mean "no relevant prior art exists." Believing the opposite would have meant reinventing tools industry already has.

## 2.1 Commercial products and vendor tooling

| Vendor / Product | What it does | Relevant gap versus our problem |
|---|---|---|
| **yieldWerx** | Implements both static and dynamic PAT, with explicit handling for normal and non-normal test-data distributions ([yieldWerx PAT guide](https://yieldwerx.com/blog/ultimate-guide-to-outlier-detection-using-part-average-testing/)) | Snapshot-based; not designed around a fixed burn-in checkpoint schedule or forward drift prediction |
| **NI TestStand Semiconductor Module** | Documents PAT as a concept, ships no default implementation ([NI docs](https://www.ni.com/docs/en-US/bundle/teststand-semiconductor-module/page/part-average-testing.html)) | Confirms this is an acknowledged, unfilled gap in at least one major commercial test platform |
| **Keysight (case study)** | Demonstrated pseudo-real-time DPAT reducing false rejects >2% in a real fab ([Keysight case study](https://www.keysight.com/be/en/assets/3121-1257/case-studies/Moving-from-Static-Limits-to-Dynamic-Part-Average-Test-PAT-Limits.pdf)) | Evidence DPAT-style methods work in practice, at automotive volume, not applied to space-grade burn-in drift specifically |
| **proteanTecs** | ML-based outlier detection using on-chip agents: learns normal device behavior and compares live measurements against predicted values, explicitly positioned as going beyond simple pass/fail and beyond PAT ([proteanTecs product page](https://www.proteantecs.com/chip-production); [white paper](https://www.proteantecs.com/resources/whitepaper-cut-defects_not-yield_outlier-detection-with-ml-precision)). A published customer case study reports that of 10 flagged outlier parts independently tested to destruction in HTOL ovens, **7 of 10 failed** — direct evidence that lot-relative/predicted-vs-measured outlier flags correlate with real reliability risk ([proteanTecs case study](https://www.proteantecs.com/hubfs/Resources%20-%20outbound/proteanTecs-CaseStudy-Outlier%20Detection.pdf?hsLang=en)) | Requires embedded on-chip monitoring agents designed into the silicon — cannot screen off-the-shelf parts after the fact, which is our situation |
| **Teradyne** | Partners with proteanTecs to bring this on-chip-agent ML telemetry directly into its UltraFLEX test platforms for real-time, on-tester decisions ([Teradyne/proteanTecs partnership announcement](https://investors.teradyne.com/news/proteantecs-and-teradyne-partner-to-bring-machine-learning-driven-telemetry-to-soc-testing/5530372f-3da1-44f7-b9a9-6bb07d5e2337)) | Real-time tester-edge infrastructure, not a standalone screening/forecasting methodology |

## 2.2 Research literature

Three research threads are directly on-topic, each cited individually where used elsewhere in this document:

**IDDQ outlier screening for burn-in reduction (Texas A&M, Sabade & Walker).** A multi-paper research program evaluated statistical outlier rejection specifically as an alternative/supplement to burn-in, using real SEMATECH industrial test data. Their foundational finding: a static 5 µA IDDQ threshold on real SEMATECH data produced **1,689 IDDQ-only failures** — chips that failed only the IDDQ test while passing every other test, and some of which had no post-burn-in data available at all, which the authors state "clearly indicates that rejecting a die based on a static threshold IDDQ test can result in considerable yield loss" ([Sabade & Walker, ITC 2001, wafer-level limit setting](https://people.engr.tamu.edu/d-walker/5yrPapers/ITC_LimitSetting_102001.pdf)). Their dedicated burn-in-reduction paper evaluates Median of Absolute Deviations (MAD) outlier rejection against delta-IDDQ and current-signature methods on the same SEMATECH data, motivated directly by the same problem this project addresses: "CMOS chips having high leakage are observed to have high burn-in fallout rate... rejecting chips that pass other tests but have high IDDQ causes unjustifiable yield loss" ([Sabade & Walker, VLSI Test Symposium 2002](https://people.engr.tamu.edu/d-walker/5yrPapers/VTS_MAD_042002.pdf)). Related papers from the same group extended this to wafer-level spatial neighbor comparison (Neighbor Current Ratio) rather than lot-relative comparison ([example](https://people.engr.tamu.edu/d-walker/5yrPapers/MWCAS_NCR_082002.pdf)) — a different reference frame than our lot-relative approach, but the same underlying statistical instinct.

**Lifetime-drift modeling for semiconductor devices (Infineon / Sommeregger & Lewitschnig).** A recent, ongoing industrial research program at Infineon Technologies Austria models exactly the "drift over stress time, used to set tighter-than-datasheet guard bands" problem this project addresses, for automotive-grade parts. Their published work spans a semi-parametric transition model using Markov-chain-based interval estimation ([Sommeregger & Lewitschnig, Microelectronics Reliability / arXiv](https://arxiv.org/html/2501.07115v1)) and an earlier RUL-prediction paper using quantile regression methods for extrapolating projected drift ([Sommeregger & Lewitschnig, ESREL 2023](https://www.rpsonline.com.sg/proceedings/esrel2023/pdf/P640.pdf)). Notably, that same literature review explicitly references "an approach using machine learning (ML) methods for regularization... proposed in Sommeregger and Pilz (2024)" as the direct precedent for applying quantile-regression-style ML to this exact problem shape — the paper trail referenced earlier in this project's research as informing our Module B design.

**A real burn-in NBTI drift experiment matching our checkpoint structure closely.** A published study stressed 300 real units across 3 fabrication lots at an elevated burn-in voltage, reading electrical parameters at pre-burn-in, 0.5h, 12h, and a cumulative 168h checkpoint at 115°C — a real experiment with a checkpoint pattern structurally close to our problem's 0h/24h/96h/168h schedule. It found NBTI-driven threshold-voltage mismatch could exceed the circuit's 2 mV design specification under burn-in stress, and states plainly that "experimental results confirm the sensitivity of the DAC circuit design to NBTI resulting from burn-in" ([Latif, Zain Ali, Hussin & Zwolinski, arXiv:1510.01370](https://arxiv.org/abs/1510.01370v1); [full text](https://ar5iv.arxiv.org/html/1510.01370)). This is used in Part 3.3 as a real-world magnitude and checkpoint-structure anchor for the synthetic generator, not as training data.

We did not find a single published system that combines lot-relative drift screening, an early-checkpoint forecast of a later reading, and QA-facing explanation, specifically for burn-in screening — which is consistent with this being a genuinely open problem, not one where a definitive prior solution was simply missed.

## 2.3 Open-source SIH peer attempts

At the time of research, multiple public repositories existed for this exact SIH statement, using broadly convergent approaches: directional/robust statistics plus Isolation Forest for Module A, gradient boosting for Module B, SHAP for explainability, and synthetic data generators of varying physical grounding. **Every one of these validated only against its own synthetic data**, with no comparison to the industry baselines described in 1.6–1.7 above, and none disclosed a documented methodology for how their synthetic data was grounded in real physics. This is precisely the two differentiation opportunities this project pursues: (a) benchmarking against real, named industry methods (PAT/DPAT, fixed delta limits) rather than only our own data, and (b) publishing a citation-backed generator methodology (Part 3) rather than an opaque one.

---

# Part 3 — Why Synthetic Data, and How to Trust It

## 3.1 There is no real dataset, and that is not our constraint — it's the problem's

The problem statement itself states no dataset is provided. We do not treat this as a shortcut forced on us; we treat it as **the actual shape of the task ISRO set**. Every legitimate team hits an identical wall. The real engineering questions this creates are: (a) can the synthetic data be defended as physically grounded, and (b) can the evaluation methodology survive scrutiny even without real data to validate against.

## 3.2 What we searched for real data, and what we found

We searched, across multiple rounds: Kaggle, Hugging Face Datasets, Zenodo, IEEE DataPort, Mendeley Data, NASA's Prognostics Center of Excellence (PCoE) repository, the PHM Society's past Data Challenge archives (spanning several years and mechanical/industrial domains — ion-mill etching, bearings, turbofans, and similar — none matching burn-in/IDDQ screening), UCI's SECOM fab-sensor dataset (a well-known public fab process-sensor set with no burn-in time-series structure), GitHub dataset searches, ISRO's own public data portals, and academic papers' supplementary materials. **None contained a real, lot-structured, Iddq/leakage/delay-over-time burn-in dataset matching this problem's schema.** The one real, closely-matching experimental dataset we did find exists only as a **published paper with 300 real units, 3 lots, and specific checkpoint readings** ([Latif et al., 3.3 below](#33-the-generators-physical-grounding)) — not as downloadable raw data, but as a genuine calibration anchor. *(Note: the exact SECOM column count and PHM Society competition list cited earlier in this project's research were not re-verified with a fresh, live source during the most recent citation pass — the general findings above are solid, but anyone citing the precise numbers externally should re-confirm them first.)*

## 3.3 The generator's physical grounding

Every distributional and mechanistic choice in the synthetic generator traces to a cited source:

| Generator element | Design choice | Source |
|---|---|---|
| Healthy-part baseline distribution | Lognormal, nested lot → die | Real Iddq measurements vary several-fold lot-to-lot even among good parts ([patent example, 5–35 µA range](https://patents.google.com/patent/US6681193)) |
| Healthy-part drift shape | Power-law, tⁿ, n randomized in [0.15, 0.30] | NBTI is "often approximated by a power-law dependence on time" ([Wikipedia NBTI](https://en.wikipedia.org/wiki/Negative-bias_temperature_instability)); real fitted exponents cluster in this range ([LJMU study](https://researchonline.ljmu.ac.uk/id/eprint/6810/1/FINAL%20VERSION.pdf)) |
| Defect activation | Arrhenius-scaled, randomized activation energy, Eₐ drawn from [0.3, 2.0] eV | JEDEC JEP122 acceleration modeling ([reference](https://moodle1.u-bordeaux.fr/pluginfile.php/971683/mod_resource/content/1/1_3qualif.pdf)). **Corrected on cross-check**: an earlier version of this document cited a narrower 0.3–0.7 eV range from a single source. Re-verified against an independent semiconductor-reliability source stating plainly that documented activation energies "vary widely... from about 0.3 eV to as high as 2.0 eV" ([reference](https://beowulf.org/pipermail/beowulf/2005-March/012172.html)), corroborated by mechanism-specific breakdowns elsewhere (surface phenomena ~0.3 eV, electromigration 0.5–0.7 eV, solder-joint intermetallics 0.8–1.1 eV, bulk diffusion up to ~1.2 eV — [reference](https://www.firgelliauto.com/blogs/calculators/accelerated-life-test-arrhenius-calculator)). The wider, better-evidenced range strengthens rather than weakens the original design choice: it is a stronger reason to randomize Eₐ per defect instance than to hard-code any single value, not a reason to narrow the range |
| Defect prevalence | 1–8% per lot, randomized | PDA conventions of 1–5% seen across real datasheets and NASA NEPP material (1.7) — treated as a wide, disclosed prior, not a precise figure |
| Lot size | 77 parts/lot default, randomizable | Derived directly (not assumed) from the standard zero-failure reliability-demonstration formula, R = (1−C)^(1/n) — solving for n at C = 90% confidence, R = 97% reliability gives n ≈ 76–77 ([formula reference](https://help.reliasoft.com/articles/content/hotwire/issue118/relbasics118.htm)); this specific unit count recurs repeatedly across real qualification-style documents, which is what prompted us to check the underlying math rather than treat it as coincidence |
| Parameter correlation | Shared "defect severity" factor for defective parts; near-independent baseline noise for healthy parts | Iddq is explicitly the *sum* of subthreshold leakage and defect current ([patent](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6489800)), while separately-specified pin/junction leakage is a much smaller, distinct mechanism ([same source](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6489800)) — related but not redundant, as reasoned in 1.3 |
| Degradation direction | All three parameters increase-is-worse | Matches the cited physics (leakage/Iddq rise with defects; delay rises with NBTI-driven Vt shift); stated scope simplification — decreasing-delay mechanisms are excluded |
| Real-world checkpoint and magnitude anchor | 168h cumulative burn-in as a plausible full-duration read point, drift magnitudes checked for plausibility against a real experiment | A real, published burn-in NBTI study used pre-burn-in, 0.5h, 12h, and cumulative 168h checkpoints across 300 real units in 3 lots, and found threshold-voltage-driven mismatch approaching or exceeding a 2 mV design specification under stress ([Latif et al., arXiv:1510.01370](https://arxiv.org/abs/1510.01370v1)) — used as a plausibility anchor, not training data |
| Guard-banding precedent for drift-based limits | Two-tier (tighter-than-datasheet) limits derived from measured drift, per Part 6.2 | Directly mirrors ongoing industrial practice at Infineon, where lifetime-drift models are used specifically to set tighter-than-datasheet guard bands from stress-test drift data ([Sommeregger & Lewitschnig](https://arxiv.org/html/2501.07115v1)) |

## 3.4 Building trust without real validation data — four concrete mechanisms

**(1) A "Synthetic Data Datasheet."** We deliberately borrow the *Datasheets for Datasets* framework from ML documentation research: "in the electronics industry, every component... is accompanied with a datasheet... by analogy, every dataset should have one" ([Gebru et al., original paper](https://arxiv.org/abs/1803.09010)). Given that we are literally building a system for screening electronic components, adopting this discipline for our own synthetic data is a natural, not superficial, fit. The datasheet content is this document (Part 3) itself, plus the disclosed-assumptions table in Part 8.

**(2) Held-out generator families, not just held-out seeds.** Evaluating a model only on random re-samples of the same generator configuration risks the model quietly overfitting our own assumptions. We instead define five **structurally different** generator configurations for validation — see Part 7, Stage 10 — following the general principle from robotics' **domain randomization** literature: training across wide simulator variability can make "the real world... appear to the model as just another variation" ([Tobin et al. 2017, original paper](https://arxiv.org/pdf/1703.06907)). We also explicitly carry forward that paper's own disclosed limitation: domain randomization narrows but does not eliminate a reality gap, and works poorly when the real world differs in *kind*, not just parameter values — which is why we pair it with (3) below rather than relying on it alone.

**(3) Benchmarking against real, named industry methods on the same footing.** Reporting "our ensemble beats static limits, fixed delta limits, and AEC-Q001 DPAT — on the same synthetic lots" is a more falsifiable, legible claim than a bare accuracy number, because a reviewer can independently check the baseline math (Part 4).

**(4) Quantitative realism validation — upgraded from a qualitative check, closing a gap we had previously only disclosed.** An earlier version of this document limited itself to a qualitative "shape resembles" comparison against real degradation curves, explicitly disclosed as "not a formal statistical validation" (Part 8.1). That gap is closeable with bounded, scriptable work, so we close it rather than leave it disclosed indefinitely: extract comparable statistical parameters from both the generator's output and the real reference data already cited in this document (the 300-unit NBTI study, 1.4/3.3) — degradation-rate distribution shape, noise-to-signal ratio, time-to-knee fraction — and compare them with a Kolmogorov–Smirnov test, reporting the actual statistic and p-value rather than an assertion. This does not upgrade the claim to "validated on real data" (3.2 already established why real burn-in-screening data and general component-aging data differ enough in structure that a full validation isn't honestly claimable); it upgrades *how rigorously* the plausibility check itself is demonstrated, from "we looked at it and it seemed close" to "here is the test statistic." Implemented as part of the generator's own test suite (E1), not a separate subsystem.

---

# Part 4 — Method Selection: Why These Models, With Evidence

## 4.1 Framing the task correctly first

Before selecting any model, it matters what *kind* of task this is. Each part contributes only a handful of scalar readings (2–4 checkpoints × 3 parameters). This is a **small-sample, low-dimensional, tabular** problem — not a long-sequence or high-dimensional one. Every model choice below follows from evidence matched to that specific regime, not from general ML popularity.

## 4.2 Module A — outlier detection

| Candidate | Evidence for inclusion | Role in our system |
|---|---|---|
| **Robust z-score** (median, IQR/1.35) | This *is* the literal AEC-Q001 industry method (1.6) | Explainable core; per-parameter, lot-relative |
| **Robust Mahalanobis distance (Minimum Covariance Determinant / MCD)** | A plain (non-robust) Mahalanobis distance is corrupted by the very outliers it should catch, because its mean/covariance are fit on contaminated data; MCD instead fits location/scale to the cleanest sub-sample and is explicitly documented to make contaminating populations distinguishable where the naive method cannot ([scikit-learn's own worked example](https://scikit-learn.org/1.7/auto_examples/covariance/plot_mahalanobis_distances.html); implementation also available in [PyOD](https://pyod.readthedocs.io/en/latest/_modules/pyod/models/mcd.html)) | Joint, lot-relative check across all three parameters together — catches a part that is unremarkable on any single parameter but anomalous in combination |
| **Isolation Forest** | Purpose-built to work well with a *small sub-sample per tree* — the original algorithm's default sub-sample size is just 256 and detection performance "converges quickly" with it ([scikit-learn documentation, citing Liu, Ting & Zhou 2008](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)) | Deliberately **pooled cross-lot** (not lot-relative like the two above) — catches campaign-level drift the other two cannot see by design; contributes nothing on a part number's first-ever lot (no history yet) |

**Dimensionality, pinned explicitly rather than left implicit.** scikit-learn's own guidance states MCD "has a low error provided **n_samples > 5·n_features**" ([Robust vs Empirical covariance estimate](https://scikit-learn.org/0.20/auto_examples/covariance/plot_robust_vs_empirical_covariance.html)). Checked against our own numbers: fitting MCD **per checkpoint** (3 features — one per parameter) needs >15 samples, safely covered even by the 30-part small-lot fallback (7.4). Fitting MCD **jointly across all checkpoints** (up to 12 features) needs >60 samples — technically fine at the default 77-part lot, but **fails at our own 30-part fallback threshold**. **Locked default: per-checkpoint MCD.** A jointly-multi-checkpoint version is a legitimate richer enhancement, not the default, and should only run when the lot-size check the fallback logic already computes confirms enough samples for the higher dimensionality.

**A fourth candidate considered for Module A itself, and correctly ruled out on reflection: kernel density estimation (KDE).** The initial case for KDE was that MCD assumes an elliptical healthy-part cluster, and our generator models several distinct defect archetypes that might look multi-modal. On closer inspection this doesn't hold: **MCD only needs the *healthy* population to be well-estimated — it does not require the anomalous population to be unimodal.** A point far from a well-estimated healthy cluster registers as anomalous regardless of how many different defect types exist or which direction they deviate in. Our generator's healthy baseline is lognormal per lot, reasonably unimodal by construction, so the specific scenario that would make KDE meaningfully better than MCD doesn't clearly apply to how the generator is actually built. Two further costs make this a clear no rather than a close call: KDE has no natural per-feature decomposition — unlike MCD's Mahalanobis distance, there is no clean way to say "which parameter drove this score," meaning it would need the same explainability-gate treatment as Isolation Forest (6.2) for a benefit that isn't clearly present; and KDE's own reliability is genuinely borderline at 3 dimensions, not comfortably inside a safe zone — research on multivariate density estimation notes estimates "become biased already beyond 2 or 3 dimensions" ([density estimation literature](https://arxiv.org/pdf/2407.08094)), with sample requirements growing sharply with dimension ([curse-of-dimensionality reference](https://theorempath.com/topics/kernel-density-estimation)). Not built; kept on record rather than silently dropped.

**A fourth Module A candidate genuinely worth adding: ECOD.** Unlike KDE, this one holds up on review. ECOD (Empirical-Cumulative-distribution-based Outlier Detection) is peer-reviewed (TKDE 2022) and its own documentation states plainly that it "is a parameter-free, highly interpretable outlier detection algorithm based on empirical CDF functions" ([PyOD source](https://pyod.readthedocs.io/en/latest/_modules/pyod/models/ecod.html); [original paper](https://arxiv.org/pdf/2201.00382v1)) — already in the same PyOD toolkit cited for Isolation Forest (4.6), so no new dependency. **A correction to how this was first framed, checked before writing it in:** "parameter-free" describes the *scoring computation* — no distributional assumptions or tuned hyperparameters govern how the empirical CDF-based score itself is produced — not the *thresholding step*. ECOD's own constructor still takes a `contamination` parameter to turn a score into a flag decision, exactly like Isolation Forest and MCD. Added as a fourth candidate in the Stage 10 harness bake-off (7.12), on the same evidentiary footing as the other three, not assumed to win.

**A gap in the z-score design, found on review: deviation direction was never addressed.** As specified, robust z-score flags deviation *magnitude* symmetrically — a part unusually far above the lot median and a part unusually far below it score identically. For a "higher is worse" parameter (1.3), these are not equally concerning: an unusually *low* reading is not the failure mode burn-in screening is built to catch, with one specific, narrow exception — a part that drifts *abnormally little* can be the signature of a part that has already burned through part of its infant-mortality life before arriving (a pre-aged/recycled-part concern), which is a distinct, separate detection question, not something the ordinary severity scale should quietly fold in. **Fix:** the severity computation is direction-aware — a below-median deviation is capped at WATCH-eligible severity by default, never REJECT-eligible, unless a dedicated pre-aged-signature check (a stretch capability, not built by default) independently flags it. This is a refinement to 4.2's existing detectors, not a new one.

## 4.2b A fourth candidate considered for cross-lot trend monitoring: CUSUM/EWMA

Beyond the three per-lot detectors in 4.2, we considered classical Statistical Process Control charts — **CUSUM** (cumulative sum) and **EWMA** (exponentially weighted moving average) — for a different job: catching a **slow drift across many lots over an entire campaign**, which none of the three per-lot detectors are built to see. Both charts exist specifically because ordinary control charts are good at large, sudden shifts but slow to catch small, sustained ones, which CUSUM and EWMA are built to detect faster by weighting past data ([JMP's statistical methods reference](https://www.jmp.com/en/statistics-knowledge-portal/quality-and-reliability-methods/control-charts/cusum-and-ewma-control-charts)). This is not a hypothetical fit for our domain — CUSUM charts are used in real semiconductor fabrication specifically because "process drift of fractions of a nanometer can cause chip failures, so early detection is critical" on parameters like wafer thickness and etch depth ([reference](https://www.visualizing.org/cusum-chart)). This became the basis for the cross-lot campaign-monitoring stretch feature (`non-essential-features.md`, N1) rather than a core Module A component, since it answers a different question (campaign health) than the statement's per-part/per-lot Module A ask.

## 4.2c Scaling beyond three parameters — audited per component, not assumed uniform

A real deployment, or the judges' own hidden test data, could plausibly involve more than three parameters. The three system components don't scale the same way, and treating them as if they did would be dishonest.

**Module A generalizes cleanly, with one precise, checkable ceiling.** Robust z-score and Isolation Forest are parameter-count-agnostic by construction — nothing about them assumes exactly three. MCD is the one to watch, and 4.2's own number gives the answer directly: at our fixed 77-part default lot, `n_samples > 5·n_features` caps *reliable joint MCD* at roughly 15 parameters before lot size itself becomes the bottleneck — a checkable ceiling, not a guess.

**Module B also generalizes, and this turns out to be a benefit of a choice made for other reasons.** One model is trained *per parameter*, not one joint model predicting all three at once (7.6). Adding a fourth parameter means training a fourth independent model, not redesigning the architecture.

**The generator does not auto-scale, and this is the part worth stating plainly rather than implying otherwise.** Each of the three parameters carries its own cited physics — NBTI power-law drift for delay, subthreshold-leakage composition for Iddq (1.3, 1.4). A fourth parameter is not "add a column, randomize a range" — it needs the same real domain grounding these three received, or it is an ungrounded guess wearing the same citation-backed presentation as the rest of the system. That is genuine research effort, not engineering effort, and is disclosed as out of current scope (Part 8.1) rather than assumed trivial.

## 4.3 Module B — drift prediction

| Candidate | Evidence | Verdict |
|---|---|---|
| Physics baselines (persistence, linear, power-law extrapolation) | Directly derived from 1.4/3.3 | **Mandatory baselines any real model must beat** |
| Gradient boosting (quantile loss) | Practical, fast, CPU-trainable, well-understood; matches the general approach used across the SIH peer landscape (2.3) | **Primary model** |
| **TabPFN** (pretrained tabular foundation model) | A single forward pass "outperforms all previous methods on datasets with up to 10,000 samples by a wide margin," explicitly built for exactly this small-tabular regime, per its original Nature paper ([Hollmann et al. 2025, PubMed abstract](https://pubmed.ncbi.nlm.nih.gov/39780007/); [overview](https://en.wikipedia.org/wiki/TabPFN)) | **Harness-only challenger** — evaluated for accuracy, not deployed live, to avoid a model-download dependency at demo time |
| Time-series foundation models (e.g. TimesFM, Chronos) | These are built around long historical context — TimesFM's published checkpoint supports **context length up to 2,048 time points**, pretrained on ~100 billion time points ([TimesFM overview](https://yuv.ai/blog/timesfm)) | **Ruled out by evidence, not assumption.** Our Module B input is 2–3 scalar readings per part — not a long series to extend, but a few-points-in-one-point-out regression. This mismatch holds *even with infinite synthetic training data*, because a fixed burn-in checkpoint schedule never produces more than 2–4 readings per part, no matter how many parts exist. |

## 4.4 Calibrating the "safety slope" — the statement's one undefined term

The problem statement asks the system to flag a part when "the predicted 168h drift rate exceeds a calculated safety slope," without defining what that calculation should be. We resolve this using **Conformalized Quantile Regression (CQR)**: it "attain[s] valid coverage in finite samples, without making distributional assumptions," combining conformal prediction with quantile regression for a calibrated, defensible interval ([Romano, Patterson & Candès 2019, official NeurIPS paper](https://proceedings.neurips.cc/paper_files/paper/2019/file/5103c3584b063c431bd1268e9b5e76fb-Paper.pdf)). The safety slope is defined as the **calibrated upper quantile of healthy-part drift rate**, not an arbitrary percentile.

**One disclosed limitation, not silently resolved:** CQR's coverage guarantee is proven under an assumption that samples are drawn **exchangeably** — the same paper states this explicitly. Our data has lot structure, a form of grouping that can violate exchangeability. We calibrate globally per part number (pooled across lots) as the default, with per-lot calibration as a fallback when a lot has enough of its own held-out points — and we disclose, rather than hide, that this does not fully resolve the theoretical gap (see Part 8).

**A verification worth doing explicitly rather than assuming, since it separates two distinct exchangeability concerns that are easy to conflate.** One version of this concern is a *time*-based failure mode: a single unit's trajectory straddling both the training set and the calibration set. Checked against our own architecture: this cannot happen here, structurally, not by discipline. Module B was never built as a per-unit time-series model — each training example already *is* one part (its 0h/24h features, its 168h target), so there is no "within-trajectory split" for it to leak across. This dimension is a confirmed non-issue, not merely an assumed one. The second version — whether units from *different lots*, pooled together for calibration, are genuinely exchangeable with each other — is a separate question this check does not resolve, and remains exactly as open as stated above. Confirming the first does not weaken the second; both are stated on their own merits, not blended into one softer claim.

## 4.5 Explainability

**TreeSHAP** computes *exact* Shapley-value feature attributions for tree-based models in polynomial time, rather than the sampling-based approximation required for arbitrary models ([Lundberg, Erion & Lee, original paper](https://arxiv.org/pdf/1802.03888v2)). It only applies to Module B's gradient-boosted model, however — not to the robust z-score (self-explanatory by construction: the z-score value *is* the explanation) or to MCD (explained instead via a per-parameter decomposition of the Mahalanobis distance, a distinct technique from SHAP). **ECOD gets a fourth, evidence-backed mechanism, not left unexplained by omission:** its own algorithm computes a per-dimension tail probability for each parameter *before* aggregating them into one score ([original paper](https://arxiv.org/pdf/2201.00382v1)) — those per-dimension values are exposed directly as ECOD's contribution breakdown, the same way MCD's distance already decomposes per parameter, not a new technique invented for it. Four explanation mechanisms, correctly matched to four different model types — not one label glossing over all of them.

**A refinement found on review: the severity-cap note (6.2) was written for only one of the two reasons a part's severity can be capped.** It was worded specifically for the Isolation-Forest-only explainability gate. Direction-awareness (4.2) introduced a second, independent reason a part can sit at a lower tier than its raw magnitude alone would suggest — a below-median deviation, capped regardless of which detector flagged it. Both need the same visible treatment for the same underlying reason: **a hidden cap protects the system's logic but not the reviewer's understanding of it.** One generalized note, worded for whichever reason actually applied to a given part — never a single note type standing in for two different explanations.

**A gap found on review: per-part explanations don't add up to a lot-level one.** The mechanisms above explain a single flagged part; none of them answer "why is *this lot* as a whole a concern." A short, templated lot-level summary (e.g., "3 of 77 parts flagged, concentrated in leakage current, 2 crossing REVIEW only") is a cheap addition over already-computed per-part outputs, not a new model.

**A second explainability channel worth adding: case-based, not just statistical.** All the mechanisms above answer "why is this number unusual." None answer "have we seen this before, and what happened." This is a recognized, distinct category in the explainability literature — **Case-Based Reasoning applied to XAI (XCBR)** — built on the premise that a single statistical explanation is often insufficient on its own to build user trust, and that retrieving and presenting similar past cases is a natural, human-legible complement to it ([XCBR survey](https://discovery.ucl.ac.uk/10214905/1/Empowering_Explainable_Artificial_Intelligence_Through_Case-Based_Reasoning_A_Comprehensive_Exploration.pdf); [example-based explanations in XAI](https://zilliz.com/ai-faq/what-are-examplebased-explanations-in-explainable-ai)). We already persist exactly what this needs — E11's stored per-part feature vectors from past lots — so this is a retrieval feature on top of existing storage, not new infrastructure. Its value is strongest when retrieved cases carry a **confirmed** real-world outcome rather than just a past model flag (an unconfirmed retrieved case risks being circular — "this resembles something we also just guessed about"), which is why its value compounds with the feedback loop (`essential-features.md` E13) rather than standing alone. Scoped as a stretch feature (N10), given the cold-start reality that a hackathon-scale demo won't have many past incidents to retrieve from early on — the same limitation already disclosed for Isolation Forest's cross-lot history (4.2).

**Considered and explicitly ruled out: an LLM synthesizing explanations into natural language.** The idea has a legitimate, narrow version — rephrasing already-computed, fully-verifiable facts into smoother prose for the report — but it was ruled out for this project specifically: it adds a network dependency to a system otherwise designed to run standalone end-to-end, and the benefit over a well-written template is marginal against that cost. More importantly, any generative step in or near the explanation path risks presenting a fabricated or embellished detail as fact in a safety-critical QA tool, which would work directly against the trust explainability is meant to build. Ruled out for the live system; not something to reconsider before the deadline.

## 4.6 Practical toolkit

[**PyOD**](https://github.com/yzhao062/pyod) is a long-running, actively maintained Python toolkit bundling dozens of outlier-detection algorithms (including Isolation Forest and MCD) under one API. Notably, it is used for **all 30 algorithms** in a real spacecraft application: the European Space Agency's OPS-SAT telemetry anomaly-detection benchmark, published in *Nature Scientific Data* (2025) ([PyOD project page, maintainer-published summary](https://viterbi-web.usc.edu/~yzhao010/pyod.html)) — a directly relevant precedent given our own space-sector context.

## 4.7 Why this is a statistical/small-sample-ML task, not a deep-learning task

Every piece of evidence gathered points the same direction: PAT/DPAT (the real industry answer) is classical statistics (4.2); MCD is specifically strong at small n; Isolation Forest is purpose-built for small sub-samples; TabPFN was purpose-built for — and specifically wins on — small tabular data; and time-series foundation models need far more historical context than a fixed burn-in schedule can ever provide (4.3).

A 2026 outlier-detection benchmark spanning thousands of datasets makes this precise rather than qualitative: shallow methods outperform deep models in **both** low- and high-dimensional regimes, but the performance gap is *larger* in low-dimensional data than high-dimensional data (average-rank gap of **2.61 in low dimensions vs. 1.70 in high dimensions**) — the opposite pattern from what "just needs more data/parameters to help" would predict, and squarely in favor of shallow methods specifically in our low-dimensional (3-parameter) regime ([MacrOData benchmark, arXiv](https://arxiv.org/pdf/2602.09329)). The same paper benchmarks foundation-model variants (including a tabular outlier-detection foundation model, TabPFN-OD) under different dimensionality and context-size regimes, reinforcing that this is a dimensionality effect, not a data-volume effect.

We treat this as the answer to "is this a deep learning task or a statistical task," settled by evidence gathered across the whole research process, not asserted upfront.

---

# Part 5 — Mirroring a Real Product, Not Just a Model Demo

## 5.1 Why this mattered enough to redesign the pipeline

An earlier version of this system's design ended at a dashboard showing a verdict. Real high-reliability screening does not work that way, for two well-documented reasons.

## 5.2 The disposition decision is always human-authorized

Aerospace nonconforming-material handling runs through a **Material Review Board (MRB)** process. An FAA Advisory Circular, quoted directly in an industry compliance forum, states that "PAHs should have procedures that ensure a material review board (MRB) is established, documented, and operational," reviewing nonconforming material to determine disposition, with senior management separately reviewing nonconformance data "to detect adverse trends" ([FAA AC 21-43, as quoted](https://elsmar.com/elsmarqualityforum/threads/as9100-control-of-non-conforming-product-personnel-who-make-disposition-decisions.46821/page-3)). A quality-systems glossary describes the MRB as deciding whether nonconforming material should be "used-as-is, reworked, repaired, returned to the supplier or scrapped," with the decision documented as auditable evidence ([MRB glossary entry](https://qt9software.com/glossary/material-review-board-mrb)). No system auto-rejects a flight part; software recommends, a qualified person authorizes. This is the direct precedent for our disposition workflow (Part 7, Stage 7).

## 5.3 The deliverable is a document, not a screen

Real component screening produces a defined **data package** as its output, not merely a live dashboard — this is the actual work product a QA organization files and can be audited against later. This shapes our Stage 8 report generator (Part 7) directly: it is built as an essential feature, not a stretch add-on, because it mirrors what the real workflow actually produces.

## 5.4 A procedural gap found by re-checking the standard: data arrives per checkpoint, not per lot

A later review asked whether our ingestion design actually matches how burn-in data accumulates in practice. It did not, fully. The real screening sequence already cited in this document has a formally named, separate step for this: the same MIL-STD-883 Method 5004 screening table used for burn-in duration (Part 1.2) also lists **"Interim Post-Burn-in Electrical Parameters"** as its own row, distinct from the final electrical test ([eesemi.com summary of Method 5004](https://eesemi.com/milscreens.htm)) — confirming that real screening data genuinely arrives in separate readout events over the course of a campaign, not as one pre-assembled table.

**Fix:** Stage 1 (7.3) now supports incremental ingestion — uploading a new checkpoint file for a lot already on record, matched by part ID into the growing per-part history, with lot status automatically flipping from In-Progress to Complete once all expected checkpoints are present. This is a correction to the ingestion design, not a new feature.

## 5.5 A procedural question the design had left silently unanswered: do early rejects count toward PDA?

The PDA formula already cited in this document (Part 1.7) defines the denominator as the total number of devices **"submitted for burn-in"** — not the number that completed it ([RH1085 datasheet, PDA Test Notes](https://html.alldatasheet.net/html-pdf/257525/LINER/RH1085/459/3/RH1085.html)). A part flagged `EARLY_REJECT` at 24h was submitted for burn-in; it simply didn't complete the full duration because the system pulled it early. Reading the standard's own wording, it should count toward the lot's failure tally.

**Fix, and the reason it matters beyond correctness:** if early rejects did *not* count, a lot could look artificially cleaner by "early-rejecting" parts before they'd ever show up in the PDA count — the opposite of what early rejection is for. Stage 5 (7.7) now states this rule explicitly.

## 5.6 Cross-functional disposition — from a role dropdown to named accounts, and why the difference matters

Real MRB practice is typically cross-functional, not a single reviewer — the same AS9100 clause quoted in 5.2 specifically asks for "the process for approving personnel making these decisions," implying an authorized roster, not an open text field. Building real authentication to match this would add security-sensitive engineering scope that none of the three judged criteria (Part 1.8) depend on, and a half-built login system tends to read as *less* credible than an honestly-labeled simplification, not more.

**First version, and why it didn't actually work.** A small roster of named reviewer roles (Quality Engineer, Reliability Engineer), selected via a dropdown at the moment of disposition, with REJECT requiring two distinct roles. On review, this doesn't hold up: nothing stops one person from selecting one role, then the other, for the same disposition — the check was on a *role label*, not on *who* was acting, so the mechanism could be satisfied by exactly the single reviewer it was meant to rule out.

**The fix: fix the role to the account at creation time, not at the moment of use.** Two named accounts exist (e.g., A. Sharma — Quality Engineer; R. Mehta — Reliability Engineer), each with a lightweight PIN. Nobody logging in *declares* a role — they can only act as an identity someone else already provisioned. REJECT requires sign-off from **two distinct account IDs**, not two role labels — closing the specific loophole a label-based check leaves open. The PIN is explicitly a speed bump, not security: hashed rather than stored in plaintext (avoiding an obviously careless pattern) but with no illusion that it resists a determined bad actor.

**The honest framing, reached by asking "is there a better way" directly: the goal is deterrence and auditability, not prevention.** No lightweight scheme, named accounts included, can *prevent* one person who knows both PINs from satisfying both roles — only real authentication infrastructure could, and that's already ruled out above. This is not a shortfall unique to our simplification: a real cross-functional sign-off is not cryptographically unforgeable either. It relies on the record being discoverable and attributable, so gaming it is a visible, accountable act, not an invisible one. Two mechanisms follow directly from that reframe: a non-blocking, visible **timing flag** in the audit log when two sign-offs on the same part land implausibly close together (default: under two minutes) — a note, never a block, since a live demo can legitimately have fast back-to-back approvals and a hard gate here would misfire in front of judges; and a **concurrency lock** around the disposition write itself, a genuine correctness gap (not a gaming concern) found while designing this — two reviewers acting on the same part within moments of each other could otherwise produce an inconsistent write.

**Named identity is reused, not duplicated, for ingestion.** The same account model answers a separate gap found while auditing the pre-ingestion sandbox (5.8): ingestion events previously had no attribution at all. Every ingestion and every disposition now ties to the same named-account ID, one mechanism, not two.

**What this deliberately does not cover, disclosed rather than left implicit:** a reviewer-unavailability/delegate rule (real MRB processes have one; a fixed two-account roster does not need one at this scale, but a larger roster would), and access scoped by part type or program — not built, because the system currently covers exactly one part family, so there is nothing to scope access *by* yet. See Part 8.1 for both, named explicitly rather than silently absent.

## 5.7 Why a screening record needs to be reopenable, not just logged

Real QA record-keeping is not a one-shot event. The same FAA guidance already cited in 5.2 continues: "senior management should review and analyze nonconforming material data to detect adverse trends" — which requires past records to be genuinely retrievable and reviewable later, not just written once to a log file. Our original Stage 9 design (7.11) planned an append-only log but not a way to reopen a past lot's full interactive state.

**Fix:** persistent storage (SQLite) is promoted from "if time allows" to a committed default, and Stage 7 (7.9) gains a project browser — a list of past lot analyses, each reloadable into the live dashboard with its original ingested data, computed features, Module A/B outputs, explanations, and disposition history intact. Each ingestion-and-analysis event becomes its own project record, the same way each real lot gets its own retrievable record in a real screening system.

## 5.8 A pre-ingestion data sandbox — decided as a private dev tool, deliberately not part of the shipped product

An early version of this idea proposed letting a reviewer directly edit data already sitting in the system of record, styled after a live-editable admin grid. That would be a poor mirror of reality: real screening data, once committed, is treated close to immutable — the correction path in a real facility is a formal retest or resubmission event, logged as new, not an in-place edit of the official number.

**A middle version was considered next:** an editable grid sitting *before* ingestion, over the synthetic generator's raw output, using Streamlit's built-in editable-dataframe widget ([Streamlit `st.data_editor` documentation](https://docs.streamlit.io/library/advanced-features/dataframes)), attributed to whoever used it. Weighed directly against removing it from the demoed application entirely: even attributed, its presence in the app a judge sees invites a fair question — "does your production system let people edit official data?" — that a clean answer avoids by construction. Given the explicit goal that the demo should mostly resemble the real product, the value it offers (fast iteration while building Module A/B, a strong "watch it react live" demo moment) doesn't require it to live inside the shipped application at all.

**Decision: kept as a private development script the team uses while building and testing Module A/B, never surfaced in the application judges see.** The legitimate live-demo need — showing the system work on a full, realistic lot — is already covered by the "load synthetic demo lot" path in ingestion (7.3), which uses a complete file exactly as real ingestion would receive one. This keeps the iteration benefit at zero cost to the demoed product's integrity, rather than trying to have the tool do both jobs at once.

## 5.9 A schema-robustness question found on review: what happens with a parameter we never modeled?

The generator, and everything trained on it, covers exactly three parameters (1.3). A real deployment — or the judges' own hidden test data — could plausibly include a parameter outside that set. The system's original design had no stated answer for this.

**The two modules don't have the same answer, and pretending they do would be wrong.** Robust z-score and MCD are generic statistical methods — they need only a numeric column and a lot to compare it against, with no physics-specific tuning required to function. Module B is different: the gradient-boosted model was trained on physics-grounded synthetic data for the three named parameters specifically, and has nothing to draw on for a parameter it never saw. **Rule: Module A extends gracefully to an unrecognized numeric column (statistical check only, no drift forecast); Module B explicitly reports drift prediction as unavailable for that column rather than producing an uncalibrated guess.** Silently attempting a forecast with no grounding would be a worse failure mode than declining, because it would present an unfounded number as if it carried the same calibration guarantee as the rest of the system.

## 5.10 Where logs actually live — one global store, not per-project silos

The natural first instinct — a separate log per project, mirroring how each lot gets its own retrievable record (5.7) — turns out to be the wrong data-layout choice, for a concrete reason: two features already committed to this design need to query *across* projects, not within one. N1 (CUSUM/EWMA) trends a lot median across many lots over time; N10 (case-based retrieval) searches every past project's flagged parts, not just the current one. Per-project silos would force both features to manually merge N separate stores later — real, avoidable complexity for no benefit now.

**Decision: a single SQLite database (already the committed choice, 7.11) with `project_id` as an indexed column on every relevant row**, not a separate store per project. Five tables, all genuinely append-only — no exceptions, per 5.15's fix:

| Table | Holds | Append-only? |
|---|---|---|
| `accounts` | account_id, display name, role, PIN hash | Set once at creation |
| `projects` | project_id, lot_id, part_number, created_at, created_by | Set once at ingestion |
| `project_data` | **analysis_run_id** (primary key), project_id, raw_ingested_data, results_json (features, every Module A detector's score and explainability tag, Module B's prediction/interval, explanations, verdict — the same structure Stage 8's JSON export produces), a computed **diff against the immediately prior run** for this project (5.15) | Insert-only — a new row per `analysis_run`, never an overwrite; "current results" is the most recent row for a project, a query, not a stored flag |
| `events` | event_id, project_id, account_id, event_type (`ingest`, `checkpoint_add`, `analysis_run`, `config_change`), timestamp, payload (for `analysis_run` events, the same diff stored in `project_data`, 5.15) | Insert-only, never edited or deleted |
| `disposition_signoffs` | project_id, part_id, **analysis_run_id** (which snapshot this decision was made against, 5.15), account_id, verdict, rationale, timestamp | Insert-only — kept separate from `events` specifically because REJECT's rule (5.6: two *distinct account IDs*) requires counting distinct accounts per part, which a generic event log makes awkward to query |
| `confirmed_outcomes` | confirmed_outcome_id, project_id, part_id, **analysis_run_id** (which run's verdict this confirms or refutes — the model's own tier, not the human's disposition, 5.17), account_id, confirmed_outcome, note, recorded_at | Insert-only — its own table rather than fields on `disposition_signoffs`, since the first version of this put mutable fields on an otherwise-immutable row (5.17); no dual sign-off required, since this records an external fact rather than a judgment call |

**No "edit" event type exists in the shipped product**, consistent with 5.8's decision — a correction to real data only ever produces a new `checkpoint_add` or re-`ingest` event, the same "corrections create a new record, never overwrite" principle already applied to dispositions (5.6), now applied consistently across every table in this schema (5.15).

**Access, stated plainly rather than left implicit:** both named accounts see every project. There is no part-type-scoped access, because the system currently covers exactly one part family (1.3) — there is nothing to scope access *by* yet, not a gap so much as nothing to build against. **Explicitly not logged:** passive views (who opened a project without acting on it) — real audit systems often separate "who looked" from "who changed," but for a two-account roster with no real access control behind it, view-logging adds real log volume for very little signal. A disclosed scope decision, not an oversight (Part 8.1).

## 5.11 Extending the same dual-authorization mechanism to configuration changes

Laying out `config_change` as its own event type (5.10) surfaced a gap that wasn't visible before: 5.6's two-distinct-account rule protects a REJECT verdict on *one part*. A change to the FN:FP cost ratio (7.12) or the PDA threshold (7.7) affects *every future lot* screened afterward — a larger blast radius than any single disposition, left unprotected by the same rule. **Fix: the identical two-distinct-account sign-off mechanism built for REJECT (5.6) extends to `config_change` events.** This reuses existing code rather than adding a new mechanism, and closes a disproportionate-impact gap found only once the logging architecture made it visible as a distinct event category.

**The mechanism had no home to act from.** 5.11's authorization rule was built before any screen existed for *proposing* a config change in the first place — a gap only visible once every feature was checked against an actual screen list (5.12). **Fix: a Settings view** (7.9), showing current values for the FN:FP ratio and PDA threshold, a "propose change" action, and — inline, not buried in the global log — that setting's own change history. A proposed change sits pending until a second, distinct account signs off, exactly as a REJECT does.

## 5.12 A gap found by checking every feature against an actual screen list: several had none

Auditing the whole design against "where does this actually appear in the app" surfaced a pattern: several features were fully specified in *logic* but never assigned a place in the *interface*. Individually minor, together enough to leave a builder inventing the app's shape from scratch. Found this way:

- **No ingestion screen was ever named**, despite E7 and the STDF stretch feature (N6) both referring to "the ingestion UI" as if it already existed somewhere in the dashboard.
- **No overall navigation structure connected the views** — login, ingestion, the lot views, project browser, history, and (5.11's) settings were each described in isolation.
- **No trigger was specified for generating the report** (Stage 8) at all.
- **The explainability gate (6.2) had no visible surface** — a WATCH verdict that resulted from the cap looks identical, in the UI as specified, to an ordinary WATCH, silently defeating the transparency the rule was built for.
- **MCD's explanation (4.5) had no defined visual**, unlike z-score's explicit table and SHAP's explanation text.
- **Two already-built features referenced dashboard locations the dashboard's own spec never listed** — the lot-level explanation summary (4.5) and the History tab (5.10).
- **N10's case-based retrieval had no defined storage to retrieve from** — the logging schema redesign (5.10) focused on identity and audit tables and never carried forward a place to persist the actual per-part computed outputs a reopened project, or a retrieval query, needs.
- **The "prediction unavailable" message (5.9) had no stated display location.**

**Fix: an explicit screen inventory**, given in full in Part 7.9, closing all of the above at once rather than patching each in isolation.

## 5.13 The storage gap this surfaced: a project's computed results had nowhere to live

The most consequential of 5.12's findings: 5.10's four-table redesign (`accounts`, `projects`, `events`, `disposition_signoffs`) was built to solve identity, attribution, and audit — and in doing so, dropped something the original Stage 9 design had: an actual place to store a project's ingested data and computed results. As specified, the `projects` table held only metadata (IDs, dates, who created it) — nothing a reopened project could actually display. The Project Browser (5.7) cannot do what it was built to do without this.

**First fix:** a `project_data` table (7.11), one row per project, holding the raw ingested data and a single results object — computed features, every Module A detector's score and explainability tag, Module B's prediction and interval, the generated explanations, and the verdict, overwritten on each re-run. **This first fix turned out to be incomplete — see 5.15, which replaces the overwrite behavior with something more consistent with the rest of the schema.**

## 5.14 Log visibility must be symmetric, or the identity mechanism doesn't do its job

Not previously stated outright, found while answering where logs can be viewed: the entire justification for named accounts (5.6) is deterrence through visibility — but that only holds if each account can see the *other's* actions, not just its own. **Rule: both named accounts see the complete History (5.10) and Project Browser, including each other's actions, with no restriction between them.** Stated explicitly now rather than left to be assumed correctly.

## 5.15 Analysis runs must be append-only too — and what "what changed" actually needs to contain

**The problem 5.13's fix left behind.** An overwritten `project_data` row means a disposition signed off against one set of numbers can silently sit next to a different set of numbers later — if a reviewer REJECTs Part 0043 against Run 1, then a new checkpoint arrives and Run 2 re-scores it, reopening the project shows Run 2's figures beside a decision that was never made against them.

**The fix: `project_data` becomes append-only, like every other table in this schema, rather than the one field that behaved differently.** Each `analysis_run` writes a **new** row, keyed by `(project_id, analysis_run_id)`; "current results" is simply the most recent row, a plain query rather than a stored flag. `disposition_signoffs` gains an `analysis_run_id` column, anchoring every decision to the exact snapshot the reviewer actually saw. This is a strictly better fix than patching in a "snapshot the key numbers onto the disposition" field would have been — that would solve staleness but leave the schema with a special case to explain; this makes every table follow the same rule, which is both simpler to state and harder to get wrong.

**Why `project_data` changes at all, stated plainly rather than treated as an edge case — this is the normal lifecycle of a lot, not an exception:**
- **Incremental ingestion is the designed path, not a correction.** A lot starts In-Progress (0h+24h), Module B runs; when later checkpoints arrive via 5.4's incremental path, the lot becomes Complete and Module A runs *for the first time* — new information appearing, not a number drifting.
- **A corrected checkpoint reading**, entered as a new `checkpoint_add` event per the no-edit rule, naturally warrants fresh analysis.
- **A deliberate re-run** — after a config change (5.11), or a model update — with one firm boundary: a config change must never *automatically* re-score past projects on its own. A REJECTed part's stored result silently shifting with no new sign-off would undermine the disposition record's integrity. `analysis_run_id` is what keeps "the config changed" and "this decision was made" as two independently-anchored facts rather than one fact that can drift.

**What "what changed" needs to actually contain, since a bare flag isn't an explanation.** Three distinct kinds of change are possible between consecutive runs, and each needs different treatment, not one generic "values changed" message: a **module activating for the first time** (Module A running once a lot completes); a **forecast resolving into an actual** (Module B's predicted 168h value compared against the real reading that has now arrived — the same predicted-vs-actual computation the trajectory chart already does, not a new one); and a **verdict moving** (WATCH↔REJECT, or a severity shift within a tier).

**This is essential, not stretch, and the earlier framing that treated the diff as a nice-to-have display feature was wrong.** MIL-STD-883's own screening table records "Interim Post-Burn-in Electrical Parameters" as its own distinct, dated row — real screening has always documented the sequence, not just the endpoint. The real data package (1.7) requires "quantity in/out by operation" per operation, and MRB oversight is explicitly expected to "detect adverse trends," which requires the trail between states to actually exist to review (5.2). **Fix:** the diff between consecutive runs is computed once, at write time, and stored — not recomputed live, and not left to a browsing UI to reconstruct. It appears in three places from that one computation: a **factual staleness note** in the live UI when a reopened project has a newer run than the one a disposition was made against (Part Detail, 7.9); an **Analysis History section in the report** (7.10) — even a single-run lot gets "1 run, no revisions," which is itself informative; and the **`analysis_run` event's log payload** (5.10), so the History screen reads as an actual record of a lot's progression rather than a bare timestamp list. A full interactive side-by-side comparison view, distinct from this, is `non-essential-features.md` N11 — a nicer way to *browse* data the essential tier already produces, not what produces it.

## 5.16 Three smaller corrections found on review, bundled here since each is a one-line fix

- **The explainability gate's note (6.2) was scoped too narrowly.** It only fired when the capped verdict ended up as WATCH. When Module A is capped *and* Module B independently corroborates to REJECT, the reviewer should still see that Module A's own contribution didn't justify it — "this REJECT relies on Module B's evidence; Module A's signal alone was not corroborated" — using the same underlying tag, adapted to whichever outcome resulted, rather than firing only in one branch.
- **Settings (5.11) didn't distinguish a pending change from a finalized one.** Fixed by reusing the disposition workflow's own pending/finalized state (5.6) rather than inventing a second one — a `config_change` with one sign-off renders differently from one with two.
- **The small-lot fallback's "roughly 30 parts" (7.4) was left approximate where a precise number was already sitting in a citation on the same page.** AEC-Q001's own guidance, already quoted in this document (1.6), is "at least 30 parts" — so the rule is now exact: fewer than 30 triggers the pooled fallback, 30 or more uses lot-relative statistics.

## 5.17 The feedback loop, built in full — visibility and a corrective step, not visibility alone

Part 8.1 has disclosed "no feedback/CAPA loop" since early in this project, with N9 offered as a partial, visibility-only mitigation. That disclosure is now closed, not just softened — both halves of the loop are committed. Two real problems were found in the first version of this design and are corrected below rather than left standing.

**Why both halves matter, not just the first.** The same FAA guidance already cited twice in this document (5.2, 5.7) is explicit that oversight means detecting adverse trends **and** determining corrective and preventive action — CAPA is the term of art for exactly this pairing, and it names the gap precisely: a system that only shows a declining accuracy number satisfies the first half of that sentence and stops.

**First correction: a confirmed outcome is its own append-only record, not a field added to an existing one.** The initial design put nullable `confirmed_outcome` fields directly on `disposition_signoffs`, filled in later when the real-world outcome became known — which is an edit-after-creation on the one table where immutability matters most, directly contradicting 5.15's "every table is now genuinely append-only, no exceptions." **Fix:** a new table, `confirmed_outcomes` — its own row per confirmation, never updated. It links to **`analysis_run_id`, not to a specific disposition** — a deliberate choice, not an oversight: the corrective step exists to inform *threshold review* (5.11's REVIEW/REJECT thresholds), which governs the **system's own verdict tier** (Module A/B → Fusion, 7.7), not the human's disposition action, which a reviewer can already override for their own reasons. Confirming an outcome measures whether the *model* called it correctly, not whether the *process as a whole* did. **Recording a confirmed outcome does not require dual sign-off** — unlike a disposition or a config change, it reports an external fact rather than making a judgment call, and attribution (who recorded it, when) already supplies the accountability that matters for a factual record.

**Second correction: the corrective trigger was a blended accuracy score, which contradicts something this document already established.** E5's harness deliberately treats blended metrics like F2 as "for monitoring only, not for tuning," precisely because a single number can hide a bad false-negative rate behind a good false-positive rate — which is the exact risk the whole 10:1 cost asymmetry exists to prevent. A blended "confirmed-outcome accuracy" percentage reintroduces that same risk in the one place meant to catch drift in it. **Fix:** track false-negative and false-positive rates among confirmed outcomes **separately**. The corrective trigger is a **confirmed-outcome false-negative rate ceiling** — the rate at which confirmed-defective parts were PASSed by the system — since that is the catastrophic case the entire design is built around; the false-positive rate is computed and shown alongside for context, never as a trigger, mirroring exactly how E5 treats F2.

**What counts as a match, stated explicitly rather than left for whoever builds it to infer:** Confirmed Defective + system verdict PASS = a miss (the case that matters most); WATCH or REJECT = caught. Confirmed Good + REJECT = a false alarm; PASS or WATCH = fine. "System verdict" here is the model's own tier (7.7), not the human's final disposition.

**Visibility.** On any past project, a reviewer can record a confirmed outcome for a part (Confirmed Good / Confirmed Defective / Unknown, a note, a date) once its real eventual result becomes known outside the system. A **worklist** — "N dispositions awaiting a confirmed outcome" — lives on the Settings screen (7.9) and links into each, so the loop fills in deliberately rather than only when someone happens to reopen the right project by chance; without this, the trend would only ever reflect whichever handful of outcomes someone stumbled into recording, not a real signal.

**Corrective.** The false-negative rate among confirmed outcomes is checked against a third live-editable Settings value (alongside the FN:FP ratio and the PDA threshold, 5.11) — an FN-rate ceiling, defaulting to **5%**, an explicit, disclosed judgment call in the same spirit as the 10:1 cost ratio, not evidence-derived. The check only activates once at least **10 confirmed outcomes** exist, so a couple of early cases can't produce a statistically meaningless alert. Crossing the ceiling does not retrain or re-threshold anything automatically; it shows as a **live-computed status on the Settings screen** — recalculated whenever the screen is viewed, deliberately not a stored, stateful alert that needs dismissing, which sidesteps re-fire behavior by not having a fire/persist lifecycle at all. Any resulting threshold change is an ordinary `config_change`, going through the same dual-sign-off mechanism already built (5.11) — corrective action does not get its own authorization path; it feeds into the one that exists. This boundary is deliberate, not a shortfall: an unaudited, self-adjusting model would be a materially larger risk than a missing feature, and would break the human-authorized-decision principle this entire design is built around (5.2). **Disclosed explicitly, since it hadn't been stated anywhere before:** this status is purely view-triggered — the system has no push or notification layer at all, so nothing surfaces unless someone opens Settings.

**The honest limit, stated rather than hidden.** There is no real field-failure data to demonstrate this against in a hackathon setting — a synthetic demo can only simulate "months later, we found out," not produce it genuinely. This caps how convincing a live demonstration of this specific feature can be, independent of whether it's correctly built.

## 5.18 A gap found by re-reading our own PDA logic: it only ever runs after the fact

Stage 5's PDA rollup (7.7) computes a lot's defective fraction against the PDA threshold — but only on Complete lots, after every part has finished the full campaign. That is exactly the moment the real question — "will this lot bust PDA?" — is least useful to ask, since the chamber-time it would have saved is already spent. The real PDA formula's own wording, already cited in this document (1.7), is about the fraction of parts **submitted for burn-in**, not the fraction that finished — and Module B's early-reject predictions (Stage 4) already produce, per part, a forecast of whether that part will breach before 168h ever arrives.

**Fix: the same PDA rollup logic also runs on In-Progress lots**, using Module B's early per-part predictions in place of final measured outcomes. This is wiring existing pieces together, not new modeling — E12's PDA arithmetic and E3's early predictions both already exist; what was missing is running the first against the second before a lot completes. The output is explicitly labeled as a **forecast**, not the final PDA figure — `LOT_ON_TRACK` / `LOT_AT_RISK` / `STOP_RUN_RECOMMENDED`, distinct wording from the Complete-lot verdict, so a forecast is never mistaken for a measured result. `STOP_RUN_RECOMMENDED` is deliberately conservative: it fires only when the **lower bound** of the forecast's own calibrated interval already exceeds the PDA limit, mirroring the same conservative-bound discipline already used for per-part early rejection (4.4) — a recommendation to halt a burn-in run early is expensive and hard to reverse, and should not fire on a point estimate.

## 5.19 What "confirmed outcome" actually means for us, made concrete

Part 5.17 built the feedback loop's `confirmed_outcomes` mechanism without specifying *how*, concretely, a confirmed outcome ever becomes known in this domain — it was left as an abstract "the real-world result became known outside the system." For ISRO's actual practice, it has a specific, named answer already established earlier in this document: **Destructive Physical Analysis (DPA)**, the lot-sample teardown already cited (1.7) as the only real source of physical ground truth about a suspected latent defect.

**This gives the feedback loop real domain content, not just a generic label.** Real DPA practice selects samples essentially at random from a lot. Our system already computes exactly the information a smarter selection would use — each part's severity score (Module A) and prediction uncertainty (Module B's calibrated interval, 4.4) — so recommending which parts are most worth the destructive teardown is a natural extension of data we already produce, not a new subsystem. A simple, explainable selection rule: the highest-severity part (confirms a suspected mechanism), the highest-uncertainty part near the WATCH/REJECT boundary (the most information gained per part destroyed), and one part drawn from the unflagged population (a control, without which a teardown finding has nothing to compare against). Each recommendation carries a one-line reason, matching the explainability discipline already used everywhere else in this design (4.5). This is built as part of E13 — it is what turns "record a confirmed outcome" from a passive, opportunistic field into an active recommendation grounded in ISRO's actual practice, which is the difference between the feedback loop being a generic mechanism and a domain-native one.

---

# Part 6 — The Combination Strategy (Three Distinct Decisions, Each Locked)

Earlier drafts of this design left "how do multiple signals combine" as a vague placeholder in three different places. Each is now a concrete, evidence-backed rule.

## 6.1 Combining Module A's three detectors into one severity score

**The theory.** Outlier-ensemble combination has two classic functions: **averaging** (reduces variance, but can dilute a genuinely strong individual signal) and **maximization** (flags a case if *any* detector is confident — the conservative, recall-preserving choice). PyOD's own documentation includes both "Average" and "Weighted Average" as built-in combination utilities alongside more advanced ensemble methods like feature bagging ([PyOD documentation excerpt on combination methods](https://github.com/qhduan/pyod)).

**Our decision.** Given the problem statement's explicit cost asymmetry (a missed defect is "catastrophic"; a false alarm just costs a retest), we default to **maximum combination**: percentile-normalize each detector's score, then take the maximum. Isolation Forest contributes to raising a flag but is never allowed to *suppress* one raised by the other two — and separately, per 6.2's explainability gate, its score alone can never drive a REJECT, because unlike z-score and MCD it has no direct, per-parameter explanation (4.5), not because it is empirically weaker as a detector. (An earlier version of this reasoning cited "Isolation Forest is the weakest of the three in low-dimensional data" against 4.2 — on review, 4.2 doesn't establish that ranking; the MacrOData evidence in 4.7 is a shallow-vs-deep comparison, not a ranking among our three shallow detectors. Corrected here rather than left standing.) This is a stated **default hypothesis**, not an unquestioned final answer — Stage 10's evaluation harness explicitly tests this against a weighted-average alternative and a supervised meta-model (feasible only because we hold synthetic ground-truth labels, unlike a real deployment), and whichever wins on held-out generator families becomes the shipped default.

**Made explicit, since a reader could otherwise be left to infer it: a component's overall severity is its worst parameter's severity, not an average across parameters.** Robust z-score is computed per parameter; MCD is already joint across all three. When these feed the maximum-combination rule above, the natural consequence is that a part's severity is already driven by whichever single parameter (or the joint MCD signal) scores worst — this was already the mechanical behavior of the design as specified, not a new rule being added here, just a consequence worth stating in its own words rather than leaving a reader to derive it from the combination logic.

## 6.2 Combining Module A and Module B into one part-level verdict

**The precedent.** Real PAT practice already uses a two-tier limit structure — a tighter internal test limit sitting inside the absolute datasheet specification limit — a pattern generally known as **guard banding** in test engineering, directly paralleling the Static-PAT-vs-datasheet-limit relationship described in 1.6.

**Our decision.** Each module gets two thresholds — a looser **REVIEW** threshold and a tighter **REJECT** threshold — both tuned via Stage 10's cost-sensitive optimization, not chosen by feel:

| Module A | Module B | Verdict |
|---|---|---|
| Below REVIEW | Below REVIEW | PASS |
| Crosses REVIEW only (either module) | | WATCH |
| Crosses REJECT (either module), or both cross REVIEW together | | REJECT → routed to disposition (Part 7, Stage 7) |

**A refinement found on review, not in the original table: explainability and severity must agree with each other.** Because Module A combines by maximum (6.1), Isolation Forest — the one detector with no direct, human-legible explanation (4.5) — can alone determine a part's Module A severity. Left unaddressed, that lets a REJECT verdict reach a reviewer with no answerable "why," directly undermining the explainability criterion in exactly the case where the cross-lot signal is what caught it. **Rule: a REJECT verdict requires corroboration from an explainable detector (z-score or MCD); Isolation-Forest-only signals cap at WATCH.** This is a stated trade-off, not a free fix — WATCH still guarantees the part reaches a reviewer (6.3), but it receives single-reviewer disposition rather than the dual sign-off a REJECT requires (5.6), so a real defect caught only by the cross-lot detector gets a lighter review path than one the other two detectors would have caught. Disclosed explicitly in Part 8.1 rather than presented as a strictly-better change.

**Where exactly this cap applies, stated precisely to remove an ordering ambiguity the table alone doesn't resolve:** the cap acts on **Module A's own tier**, before the fusion table runs — an Isolation-Forest-only signal can never register as "Module A: REJECT-tier" for fusion purposes, only as "Module A: REVIEW-tier" at most, regardless of raw score magnitude. This composes correctly with the table's last row without a special case: if Module A is capped at REVIEW *and* Module B independently also crosses REVIEW, "both cross REVIEW together" still correctly fires REJECT — that path is legitimate, because the corroboration comes from Module B's own explainable evidence (SHAP-backed), not from bypassing Module A's cap. The gate blocks Module A from single-handedly reaching REJECT on an unexplainable signal; it does not block Module B from doing its own, separately-explainable part of a joint REJECT.

**The disposition UI must show this cap when it fires, not just its result — a gap found when checking where in the app this logic actually surfaces (Part 5.12), and initially scoped too narrowly even after that fix (Part 5.16).** A verdict of WATCH that resulted from this cap is not the same situation as an ordinary WATCH, and hiding the distinction defeats the purpose of building the rule (Part 7.9). The note must also fire when the *combined* verdict is REJECT via Module B's independent corroboration — the reviewer should still see that Module A's own contribution didn't justify it alone, worded to match: "this REJECT relies on Module B's evidence; Module A's signal alone was not corroborated."

## 6.3 Combining Module A and Module B for reviewer triage — deliberately *not* combined

A third combination point existed implicitly and was not properly decided until audited: how should a reviewer's part-ranking list work when Module A and Module B each produce their own severity signal? **Decision: they are shown as two separate ranked lists**, not merged into a single number. Both lists contain the same set of flagged parts (every WATCH and REJECT part); they differ only in sort order — one ranked by Module A's severity score, the other by Module B's — not in membership. Collapsing "already anomalous now" (Module A) and "predicted to drift into risk" (Module B) into one score would hide exactly the distinction a QA inspector needs to reason about and would work against the explainability evaluation criterion (1.8) rather than for it.

---

# Part 7 — The Complete, Locked App Flow

## 7.1 Architecture

```
                              ┌─────────────────────────┐
                              │  Stage 0: Generator      │  (offline, built first)
                              │  + Stage 10: Harness     │  (offline, feeds thresholds)
                              └───────────┬──────────────┘
                                          ▼
                    (dev-only, not shipped) Pre-Ingestion Sandbox — team's own build/debug tool
                                          ▼
Stage 2: Feature Engineering ← Stage 1: Ingestion ← [Screen: Ingest] ← Named-account login [Screen: Login]
                                          ▼
        ┌─────────────────────────────────────────────────┐
        │  In-Progress lot (0h+24h)     Complete lot (all) │
        │  → Module B only              → Module A + B     │
        └─────────────────────────────────────────────────┘
                    ▼                              ▼
         Stage 4: Module B                Stage 3: Module A
                    └──────────────┬───────────────┘
                                    ▼
                    Stage 5: Fusion & Verdict (two separate rankings, explainability gate)
                                    ▼
                    Stage 6: Explainability
                                    ▼
                    [Screen: Lot Dashboard] → [Screen: Part Detail] → disposition (dual sign-off)
                                    ▼
              Stage 8: Report  +  Stage 9: Storage (project_data + 4 audit/identity tables)

Reachable from the app's persistent navigation shell after login, alongside Lot Dashboard:
  [Screen: Project Browser]   [Screen: History]   [Screen: Settings] (config, dual sign-off, 5.11)
```

**Every screen named above is enumerated once, with what it shows and what feature owns it, in Part 7.9** — the fix for the gap identified in 5.12, where several features referenced "the dashboard" without the dashboard's own spec ever listing them.

**The most important architectural decision in this design**, easy to miss on a first read of the problem statement: Module A (full time-series screening) and Module B (early-checkpoint forecasting) do not run at the same moment in the real burn-in timeline. Module B's entire purpose — flagging a part for **early rejection** — requires it to run *before* 168h data exists at all. Module A's framing, screening the *complete* recorded time series, implies post-hoc analysis once burn-in finishes. The ingestion stage (7.2) encodes this explicitly via a lot-status field, rather than presenting both modules' outputs as if they were simultaneous.

## 7.2 Stage 0 — Synthetic Data Generator

Full grounding for every element is in Part 3.3. Summary of locked parameters: 3 parameters (Iddq, leakage current, propagation delay); 77 parts/lot default (randomizable), 3–10 lots per run; lognormal nested baseline variation; power-law healthy drift (n ∈ [0.15, 0.30]); Arrhenius-scaled defect archetypes at 1–8% prevalence, some activating only after 24h; tester-offset correction, quantization, and proportional measurement noise; elapsed time stored as an explicit numeric input (not a fixed column identity), to support irregular checkpoint schedules gracefully; output as wide-format CSV with hidden ground truth kept separate from the production-facing schema; five held-out generator families for validation (baseline / wider exponent range / higher defect prevalence / different noise regime / altered correlation structure).

## 7.3 Stage 1 — Ingestion

Primary path: lot-file CSV upload plus a metadata form (part number, lot ID, manufacturer, date code, test date, per-parameter units). Secondary path: a "load synthetic demo lot" button for judges without a file on hand. **Incremental ingestion**: a new checkpoint file for a lot already on record is matched by part ID into that lot's growing history, per Part 5.4. A **lot status field** — In-Progress (0h+24h only) vs. Complete (all checkpoints) — auto-updates as checkpoints accumulate and determines which module(s) run, per 7.1. Every ingestion event is attributed to the logged-in named account (Part 5.10), the same mechanism used for disposition sign-off. Schema validation gives visible errors rather than failing silently; column names are fuzzy-matched; units are normalized to a canonical form before anything downstream sees the data; duplicate/missing-value checks run before feature engineering; the system is scoped per part number, with cross-lot history (Isolation Forest, Stage 3) never pooling across different device types. The pre-ingestion sandbox (Part 5.8) is a private development tool used while building Module A/B — it is not part of this stage or the shipped application.

## 7.4 Stage 2 — Feature Engineering

Delta features per parameter (Δ24h, Δ96h if present); lot-level robust statistics (median, IQR/1.35) per parameter per checkpoint, with an explicit **small-lot fallback**: **fewer than 30 parts** (the exact AEC-Q001 minimum, 1.6, 5.16 — not an approximation) triggers a pooled cross-lot reference for that part number, visibly flagged in the UI rather than silently substituted; 30 or more uses lot-relative statistics directly; per-part robust z-scores at each available checkpoint; the joint feature vector for MCD; Module B's input vector of `[Value_0h, Value_24h, (Value_96h), lot_median_0h, lot_median_24h, elapsed_hours]`.

## 7.5 Stage 3 — Module A (outlier ensemble)

Full model rationale in Part 4.2, combination rule in Part 6.1. Robust z-score and MCD operate lot-relative; Isolation Forest operates pooled cross-lot (intentionally, to catch campaign-level drift the other two cannot see by design) and contributes nothing on a part number's first-ever lot (cold-start rule). Two severity tiers (REVIEW, REJECT) per Part 6.2, tuned in Stage 10.

## 7.6 Stage 4 — Module B (drift prediction)

Full model rationale in Part 4.3–4.4. Physics baselines must be beaten by the deployed model. Primary model: one global gradient-boosted model per part number (not separate per-lot models — a global model with lot-context features as inputs generalizes better and avoids starving small lots of training signal). Safety slope from CQR, calibrated per Part 4.4. TabPFN evaluated as a harness-only challenger. **The gap between the physics baseline and the live model's prediction is exposed as a confidence signal** — both are already computed for every part (the baseline as the bar the model must beat, per 4.3), so surfacing their disagreement costs nothing beyond reporting a number already available, and gives Stage 6's explanation a second, independent confidence proxy alongside the CQR interval width.

## 7.7 Stage 5 — Fusion & Verdict

Verdict table from Part 6.2, worst-parameter-wins per 6.1. Lot-level rollup against a PDA threshold (default 5%, adjustable — grounded in the real PDA conventions of Part 1.7) produces a suggested lot disposition. **Early-rejected parts (Module B, Stage 4) count toward the PDA failure tally**, per Part 5.5 — they were submitted for burn-in even though the system pulled them before 168h. **The same rollup also runs on In-Progress lots** using Module B's early predictions, producing a distinctly-labeled forecast (`LOT_ON_TRACK` / `LOT_AT_RISK` / `STOP_RUN_RECOMMENDED`) rather than the Complete-lot's measured verdict — see Part 5.18. **Below-median deviations are capped at WATCH-eligible severity by default** (Part 4.2's direction-awareness fix), never REJECT-eligible on that basis alone. Triage display kept as two separate rankings, per Part 6.3.

## 7.8 Stage 6 — Explainability

Per Part 4.5: TreeSHAP for Module B's gradient-boosted model; self-explanatory z-scores; a dedicated per-parameter Mahalanobis-distance decomposition for MCD. A QA-facing sentence template combines all three into plain language (e.g., "24h leakage is 4.2 robust-σ above lot median; predicted 168h drift exceeds the calibrated safety slope by 38%"), with a confidence qualifier drawn from the CQR interval width.

## 7.9 Stage 7 — QA Review Dashboard: the complete screen inventory

Seven screens, reachable through one navigation shell behind login — the explicit list that 5.12 found missing.

1. **Login.** Select one of two named accounts (5.6), enter PIN.
2. **Ingest.** Lot-file CSV upload or incremental checkpoint upload, plus the metadata form (7.3); the "load synthetic demo lot" button lives here too. Attributed to the logged-in account.
3. **Lot Dashboard.** The active lot's view, auto-selecting Early-Check (In-Progress, Module B only) or Full Disposition (Complete, both modules) per its status. Contains: the Lot Summary panel (metadata, overall verdict, flagged-part count, PDA result, the lot-level explanation summary from 4.5, and N1's cross-lot trend chart if built); the two severity-ranked lists, same flagged parts, different sort order (6.3); a **Generate Report** button (triggers Stage 8); and, on Complete lots only, a **Generate DPA Work Order** action (5.19) producing the 3-part recommendation for that specific lot — a lot-level action, distinct from the Settings screen's cross-lot worklist below, which only tracks which past dispositions are still awaiting a confirmed outcome, not where a recommendation is generated.
4. **Part Detail**, opened from either ranked list. Trajectory chart (predicted vs. actual), z-score table, an MCD per-parameter contribution chart, an **ECOD per-dimension contribution chart** (4.5 — its own visual, the same reasoning as MCD's), the SHAP-driven explanation sentence with its confidence qualifier, the **physics-vs-model disagreement gap** (4.3/7.6) shown alongside the CQR interval as a second confidence signal, a case-based retrieval panel if N10 is built, and — when they apply — three specific notes: a **severity-cap note**, generalized to whichever reason applied — the explainability gate (an unexplainable detector alone, 6.2) or direction-awareness (a below-median deviation, 4.2) — never a single wording standing in for both; an **unavailable-forecast note** for any parameter outside the trained three (5.9); and a **staleness note**, backed by the stored diff (5.15), naming exactly what changed since a signed-off decision — not a bare flag. The disposition action (Accept / Hold / Reject, rationale, dual sign-off on REJECT) and, on a past disposition, the action to **record a confirmed outcome** (5.17, its own record, not an edit to the disposition) live here.
5. **Project Browser.** Every project on record; opening one reloads screens 3–4 from the most recent `project_data` row for that project (5.15), not a fresh computation.
6. **History.** The full `events` and `disposition_signoffs` log, visible identically to both accounts (5.14) — no filtering by who's currently logged in. `analysis_run` entries carry the stored diff (5.15), not just a timestamp.
7. **Settings.** Three live-editable values under dual sign-off (5.11): the FN:FP cost ratio, the PDA threshold, and the confirmed-outcome false-negative rate ceiling (5.17). A proposed change is visually distinguished from a finalized one (5.16), reusing the disposition workflow's own pending-state. A **worklist** of dispositions awaiting a confirmed outcome (tracking only — generation happens per-lot on screen 3), and a **live-computed corrective status** — recalculated on view, not a stored alert — appear here (5.17).

## 7.10 Stage 8 — Report Generation

Per Part 5.3: report reference ID, part number, lot ID, date code, manufacturer, test date, methodology summary, quantity screened/flagged, PDA result, full delta-data table, per-flagged-part explanation and disposition, overall lot disposition, reviewer/date block — exported as PDF, with the raw CSV attached as the underlying data record. **An Analysis History section (5.15) is included for every lot**, listing each run, what triggered it, and what changed from the run before — "1 run, no revisions" for a lot analyzed once, a real changelog otherwise; capped at the **most recent 10 runs** in the printed PDF ("showing last 10 of N — full history in the JSON export or the History screen"), so an extensively re-analyzed lot doesn't produce an unbounded document. JSON export alongside the PDF/CSV carries the same content, and is the same object stored as `project_data` (5.15) — one artifact, not two copies.

## 7.11 Stage 9 — Persistent Storage: Global Log & Project State

SQLite persistence is a **committed default**, not conditional on time remaining, per Part 5.7. A single global database, not per-project silos, per Part 5.10 — `project_id` is an indexed column, since N1 and N10 both need to query across projects, not just within one. Six tables, **all genuinely append-only, no exceptions** (5.15): `accounts` (identity and role, Part 5.6), `projects` (one row per lot's metadata), `project_data` (one row per **analysis run**, not per project — features, per-detector scores and explainability tags, predictions, explanations, verdict, and a computed diff against the prior run, in the same shape as Stage 8's JSON export), `events` (append-only: ingestion, checkpoint additions, analysis runs carrying the same diff, and **config changes**, each attributed to a named account), `disposition_signoffs` (linked to the specific `analysis_run_id` a decision was made against, 5.15), and `confirmed_outcomes` (linked to `analysis_run_id`, not to a disposition — its own table, not fields on an existing one, since the feedback loop measures the model's verdict, not the human's decision, 5.17). Both accounts see the complete log and every project, symmetrically (Part 5.14).

## 7.12 Stage 10 — Evaluation Harness

Runs entirely offline, feeding both the shipped model defaults and the PPT's evidence. Tests Module A and Module B against the named industry baselines (Part 1.6, Part 4.3) across the five held-out generator families (7.2). Resolves the Module A combination-strategy question (Part 6.1) empirically. Threshold tuning is driven by **one locked cost function** — a stated False-Negative : False-Positive cost ratio, default **10:1**, an explicit, disclosed judgment call (the problem statement gives no formula for this), adjustable, not evidence-derived. Other metrics (e.g. F2) are reported for monitoring but do not drive the threshold search, to avoid the ambiguity of optimizing against several targets at once. **Recall at a fixed flag-rate is reported alongside**, giving a second, complementary view of the same operating point rather than relying on the cost-weighted score alone.

**A named, literal test the harness must include, not just imply: the problem statement's own worked example.** A lot with median leakage 10 µA and a part reading 45 µA, against a 50 µA datasheet limit, must be flagged. This is the single most direct, checkable demonstration of compliance available — every one of the peer approaches reviewed independently converged on encoding this exact case as a test, which is itself a signal that it's the first thing a domain-literate reviewer would check by hand.

**A precision found on review: threshold-tuning stability needs a guaranteed minimum per defect archetype, decoupled from how much data exists for the live demo.** With a handful of true positives, "caught 3 of 4 known defects" and "caught 4 of 4" look identical in casual reporting but are a 25-point recall swing — the threshold search and any per-archetype accuracy claim are only as stable as the smallest archetype's sample count. This is a harness-construction requirement, not a training-data-volume one: the safety slope itself (4.4) is calibrated from the abundant healthy-part population and is unaffected. The harness generates held-out test sets with an explicit minimum count of each defect archetype (1.4, 3.3), independent of however many lots the live demo dataset happens to contain.

## 7.13 Tech stack

| Layer | Choice |
|---|---|
| Data generation / features | NumPy, pandas, SciPy |
| Module A | scikit-learn (`RobustScaler`, `MinCovDet`), [PyOD](https://github.com/yzhao062/pyod) (Isolation Forest and others) |
| Module B | LightGBM (quantile loss), MAPIE for CQR, `tabpfn` (harness only) |
| Explainability | `shap` |
| Report | `fpdf2` — resolved in favor of the zero-system-dependency option over `weasyprint`, per `IMPLEMENTATION_PLAN.md` Part 3 |
| Audit / storage | SQLite |
| API | **FastAPI**, resolved as the primary build, not conditional |
| Frontend | **React** + Vite + TypeScript, resolved as the primary build |

**Revised decision, and why, stated explicitly rather than left as a silent swap:** the original plan (immediately below, kept as history) made Streamlit the default specifically for speed, with React + FastAPI gated behind "only if schedule allows." That reasoning was sound at the time; it was revisited once real REST endpoints stopped being a stretch nice-to-have and became the actual choice. Three things changed the calculus, not one:

1. **The contract-drift risk a hand-built REST layer would normally carry doesn't apply here.** FastAPI derives its OpenAPI schema directly from the same Pydantic models already used for internal validation, and a generator (`openapi-typescript` + `openapi-fetch`) turns that schema into a typed TypeScript client automatically — the frontend's contract is generated *from* the backend's, not hand-maintained in parallel where it could drift. This is a materially stronger fit for this project's own zero-ambiguity-in-shape principle (`IMPLEMENTATION_PLAN.md` R1) than Streamlit's function-signature "endpoints" ever were, since those still required each screen's code to independently stay in sync with what a function returned.
2. **A working UI is judged in the Software category**, and a React frontend consuming a real API is a closer match to what a production screening tool would actually look like — the same "resemble the real product" principle already used to justify the report generator (5.3), the named-account dual sign-off (5.6), and the audit trail (5.10), extended one layer further.
3. **The team resplit that made this affordable.** Moving the UI off P5 (already the largest-scope role under the old split) and onto P1 — who is critical-path only through the Generator and otherwise "light," per the original load-imbalance note below — turns a schedule-risking addition into a genuine rebalancing. See `IMPLEMENTATION_PLAN.md` Part 2 for the resulting split, and its own honest disclosure that this simply relocates the load-imbalance risk to P1 rather than eliminating it.

**The real cost, disclosed rather than glossed over:** a browser talking to a separate server needs a session mechanism Streamlit never did. The resolved choice is a JWT held in memory on the frontend (never `localStorage`, never a cookie) — logged out on a hard refresh, no token revocation, no refresh-token rotation. This is a deliberate, scoped-down version of real session management, consistent with E10's PIN already being "a deterrence speed bump, not security" — not a new simplification standard being introduced, the same one extended to a new surface. See Part 8.1 below for this stated as a formal disclosed simplification.

### Original decision — superseded, kept only as history

| Layer | Choice |
|---|---|
| Dashboard | Streamlit + Plotly by default; React + FastAPI only if schedule allows after modeling is complete |

This was the right call under the assumption that a real REST layer would need to be hand-specified and hand-maintained separately from the internal contracts — true for a typical Flask/Express pairing, not true once FastAPI's auto-derived schema removed that specific cost (point 1, above). `IMPLEMENTATION_PLAN.md` Part 3 is now the authoritative stack table — kept current as the build proceeds, unlike this row, which is left here only so the reasoning trail isn't lost.

## 7.14 Team split — superseded, kept only as history

The six-way split below (A–F) was the original plan, written before the team structure changed to a supervising Lead plus five developers, with the Lead handling integration, a second problem statement, and the PPT in parallel. **`IMPLEMENTATION_PLAN.md` Part 2 is now the authoritative team structure** — kept current as the build proceeds, unlike this table, which is left here only so the reasoning trail isn't lost.

| Person | Owns | Depends on |
|---|---|---|
| A | Stage 0 + Stage 10 | Nothing — build first; defines the schema contract everyone else builds against |
| B | Stage 3 | A's data |
| C | Stage 4 | A's data |
| D | Stage 5 + Stage 6 | B and C's outputs |
| E | Stage 1 + Stage 2 + Stage 8 | A's schema; feeds B/C, consumes D |
| F | Stage 7 + Stage 9 + demo/PPT integration | Everyone |

Day-1 priority: A and E must agree on the exact data schema together before anyone else starts, since that contract is what makes the rest of the split parallelizable.

---

# Part 8 — Scope Simplifications and Disclosed Assumptions

No design is free of simplification under a fixed deadline. What follows is the complete, honest list — not hidden, and each entry states what the fuller version would look like.

## 8.1 Simplifications, by area

| Area | Simplified to | Fuller version would be |
|---|---|---|
| Generator | 3 parameters, chosen primarily to match the statement's own named examples (1.3) | No formal feature-selection study across a wider candidate pool; a scope decision, not a data-driven result |
| Generator | One generic "defect severity" mechanism per defective part | Real failure physics has several distinct signature classes (e.g. TDDB, electromigration, hot-carrier injection) with different per-parameter fingerprints |
| Generator | No wafer-position spatial clustering | Real defects can cluster spatially; we model lot/die randomness only, not physical wafer position |
| Generator | Does not auto-scale beyond three parameters (Part 4.2c) | A fourth parameter needs the same real physical grounding these three received (research effort), not just a new column (engineering effort) |
| Module A | Three detectors (z-score, MCD, Isolation Forest) | [PyOD](https://github.com/yzhao062/pyod) alone offers 50+ algorithms; three were chosen on evidence (Part 4.2), not exhaustively benchmarked against all available options |
| Module A | Kernel density estimation considered and ruled out (Part 4.2) | Its own reliability is borderline at 3 dimensions, it lacks a clean per-feature explanation, and the scenario it would help with doesn't clearly apply to our lognormal, unimodal generator design |
| Module A | Simple max-combination as the default | More adaptive ensemble-combination methods exist in the literature; left as a harness-testable extension, not built by default |
| Module A | Isolation-Forest-only signals capped at WATCH, never REJECT alone (Part 6.2) | A real trade-off, not a free fix — a defect caught solely by the cross-lot detector gets single-reviewer disposition instead of the dual sign-off a REJECT would trigger, in exchange for never issuing an unexplainable REJECT |
| Module A | MCD fit per-checkpoint (3 features), not jointly across all checkpoints (Part 4.2) | Jointly-multi-checkpoint MCD is a richer, legitimate enhancement, gated behind a lot-size check, not the default — the default keeps reliable coverage down to the 30-part fallback threshold; also caps reliable joint MCD at roughly 15 parameters at our default lot size (Part 4.2c) |
| Module A | Equipment-fault discrimination is a stretch feature | The MVP cannot yet separate "real defect" from "measurement/board artifact" — a real QA inspector's likely first question |
| Module B | Only gradient boosting is deployed live | TabPFN is evaluated but not shipped, to avoid a model-download dependency at demo time — a logistics decision, not a claim that it performs worse |
| Module B | CQR calibrated globally per part number | Does not fully resolve the lot-exchangeability gap (Part 4.4); group-conditional/Mondrian conformal methods exist in the literature but were not implemented |
| Module B | Declines to forecast for any parameter outside the trained three (Part 5.9) | Module A extends gracefully to an unrecognized numeric column; Module B does not, and says so explicitly rather than producing an uncalibrated guess |
| Explainability | Statistical explanations only (z-score/MCD/SHAP); no physical defect-mechanism narrative | Answers "how unusual," not "what kind of defect this looks like" — the latter is N4, a stretch feature |
| Explainability | LLM-based narrative synthesis considered and ruled out (Part 4.5) | Adds a network dependency for marginal benefit over a template, and any generative step near the explanation path risks presenting an unverified detail as fact — not reconsidered before the deadline |
| Fusion | Two discrete verdict tiers, not a continuous risk score | Chosen for QA legibility over statistical completeness |
| Identity | Two named accounts with a PIN, fixed role at creation (Part 5.6) | The PIN is a deterrence/auditability speed bump, hashed rather than plaintext, explicitly not real authentication — cannot *prevent* one person who knows both PINs from satisfying dual sign-off, only make doing so a visible, attributable act |
| Identity | No reviewer-unavailability/delegate rule | A real MRB process has one; not needed at a fixed two-account roster, would be needed at a larger one |
| Identity | No access scoping by part type or program | The system currently covers exactly one part family (1.3), so there is nothing to scope access *by* yet — not a gap so much as premature to build |
| Auth (React↔FastAPI boundary, added with the tech-stack revision, 7.13) | A JWT held in memory on the frontend only, no revocation, no refresh-token rotation, logs out on a hard refresh | A production system would need token revocation (a blacklist or short-lived tokens with server-tracked refresh), which needs a server-side session store this design deliberately doesn't add, consistent with E10's PIN already being a deterrence measure, not real security |
| Settings | Live-editable via dual sign-off: FN:FP cost ratio, PDA threshold, and confirmed-outcome FN-rate ceiling only (Part 5.11, 5.17) | Lower-stakes tunables (the small-lot fallback size, the timing-flag window) remain code-level constants, not exposed in Settings — the three live-editable values were chosen specifically because they affect every future lot or every future corrective decision, per 5.11's reasoning; the others don't carry the same blast radius |
| Storage | Single global SQLite store, `project_id`-indexed, six tables, committed as default (Part 5.7, 5.10) | Not an immutable, cryptographically verifiable enterprise ledger; a single-node database, not a distributed system of record |
| Storage | Passive project views are not logged (Part 5.10) | Only actions (ingest, analyze, disposition, config change) are logged; "who merely looked" is not tracked |
| Storage | No log retention or backup strategy | An insert-only log grows indefinitely with no pruning, and the single SQLite file has no replication — a real production concern, correctly out of scope here |
| Ingestion | CSV as the primary format, now with incremental per-checkpoint upload (Part 5.4) | STDF (the real industry test-data container format) is a stretch feature, not core |
| Ingestion | Pre-ingestion editable sandbox is a private development tool, not part of the shipped application (Part 5.8) | Kept for the team's own build/debug speed; deliberately excluded from what judges see, since even attributed, an editable grid on official-looking data would misrepresent how real ingestion works |
| Real-data calibration | Upgraded from a qualitative "shape resembles" comparison to an actual Kolmogorov–Smirnov test against real reference data (Part 3.4) | Still not a claim of "validated on real data" — the KS test checks plausibility of shape/rate statistics, not full validation, and the reasons a full validation isn't honestly claimable (3.2) still hold |
| Module A | Deviation direction now affects severity — below-median deviations capped at WATCH, never REJECT-eligible on that basis alone (Part 4.2) | The one exception (a pre-aged/recycled-part signature) is a stretch capability, not built by default, so the cap is unconditional until that capability exists |
| Lot disposition | Early PDA forecast on In-Progress lots (Part 5.18) | A forecast, not the measured figure — distinct verdict wording enforced specifically so the two are never confused in the UI or report |
| Process | Feedback/CAPA loop built in full — visibility (`confirmed_outcomes`, its own append-only table, and a worklist) and corrective (a Settings-screen status when the confirmed-outcome false-negative rate crosses a ceiling) (Part 5.17) | The corrective step raises a visible status only — it never auto-adjusts a threshold; any resulting change is an ordinary `config_change` requiring the same dual sign-off as everything else, a deliberate boundary consistent with the human-authorized-decision principle (5.2), not a shortfall |
| Process | FN-rate ceiling defaults to 5%, active only once 10 confirmed outcomes exist | Disclosed judgment calls, same treatment as the 10:1 FN:FP ratio — not evidence-derived |
| Process | The corrective status is purely view-triggered | The system has no push or notification layer at all; nothing surfaces unless Settings is opened |
| Process | No real field-failure data to demonstrate the feedback loop against | A synthetic demo can only simulate "months later, we found out," not produce it genuinely — caps how convincing a live demonstration can be, independent of whether the feature is correctly built (5.17) |

## 8.2 Is simplification the right call here?

Yes, as the default position, for two evidence-based reasons: (1) the explainability criterion (1.8) rewards a system the team can fully defend live, not maximum complexity; (2) most cuts above were informed by evidence about where complexity does not pay off — e.g., three detectors rather than fifty, because low-dimensional-data literature already shows shallow methods hold their advantage there (Part 4.2). Two cuts are not free, and should be treated as anticipated-question material rather than hoped-past: **equipment-fault discrimination** being a stretch feature leaves a real, likely QA question unanswered by the MVP; **CQR's exchangeability gap** directly touches the rigor of the Drift Prediction Accuracy criterion's calibration claim.

## 8.3 Evidence-thin items — disclosed explicitly, not upgraded to "proven"

- **Noise-floor magnitude** in the generator — no source gave an exact ATE noise percentage; set as an adjustable default.
- **Defect prevalence range (1–8%)** — anchored to real PDA conventions (1.7) but genuinely uncertain in exact value.
- **FN:FP cost ratio (10:1)** — an explicit, disclosed judgment call; the problem statement provides no formula.
- **GBM-over-TabPFN as the live model** — a logistics decision (demo reliability), not a performance claim.
- **CQR's lot-exchangeability gap** — disclosed, not solved (4.4, 8.1).

## 8.4 The one thing that cannot be closed by more reasoning

Whether our generator's assumptions match whatever the judges' own hidden evaluation data looks like is **irreducible** — it cannot be verified in advance by either side. The mitigation is everything in Part 3.4 and Part 7.12: held-out generator-family testing, benchmarking against real named industry baselines, and a fully disclosed assumption list so a reviewer can judge the *reasoning* even without matching our exact numbers.

---

# Part 9 — Requirement Traceability

| Statement requirement | Satisfied by | Where |
|---|---|---|
| Module A: dynamic outlier detection | Robust z-score + MCD + Isolation Forest ensemble | Part 7.5 |
| Module B: drift predictor, safety slope, early rejection | Gradient boosting + CQR-calibrated safety slope | Part 7.6 |
| Anomaly Detection Score (false negative catastrophic) | Cost-sensitive threshold (10:1 default), tuned in harness | Part 6.2, Part 7.12 |
| Drift Prediction Accuracy (MAE) | Evaluation harness, reported against baselines | Part 7.12 |
| Explainability ("justify to a QA inspector, or black box") | SHAP/z-score/MCD explanations feeding an actual human disposition decision, not just a displayed paragraph | Part 7.8, Part 7.9 |
| Software category | Full ingestion → review → report working application | Part 7 entire |

---

# Appendix — Glossary

- **Burn-in**: operating a component at elevated temperature/stress for an extended period before acceptance, to force out latent manufacturing defects.
- **Iddq**: quiescent (idle-state) supply current of a CMOS device.
- **PAT / DPAT**: Part Average Testing / Dynamic PAT — the AEC-Q001 industry method for lot-relative outlier screening (Part 1.6).
- **PDA**: Percent Defective Allowable — the lot-level accept/reject threshold used in real screening flows (Part 1.7).
- **MRB**: Material Review Board — the human-authorized nonconforming-material disposition process in aerospace QA (Part 5.2).
- **CQR**: Conformalized Quantile Regression — the calibration method used for our "safety slope" (Part 4.4).
- **MCD**: Minimum Covariance Determinant — a robust covariance estimator used for multivariate outlier detection (Part 4.2).
