# WiFi Sensing and Identity — Research Notes

Research into whether WiFi signals can be used to (a) detect a human body and
(b) identify which specific person is present. The goal was to decide what role, if
any, WiFi sensing plays in the platform, and where identity should come from.

Summary of what the research established:

- Identity (who a person is) comes from network authentication (login), not from the
  WiFi signal.
- Anonymous presence (whether a body is in a zone) is achievable with WiFi sensing where
  the hardware supports it, and is used only as confirmation — never to identify anyone.
- Using WiFi to identify a specific person by their body is not viable at the scale a
  workplace product needs. This was tested from several angles and each reached the same
  limitation.

---

## Can Cisco enterprise APs output raw CSI?

Technically possible, but not through any supported path. Standard Cisco firmware
(IOS-XE, Meraki) is built for management and security rather than raw physical-layer
extraction. Obtaining raw Channel State Information (CSI) requires either flashing
open-source firmware such as nexmon_csi onto specific older Broadcom-chipset access
points (e.g. Aironet 2800/3800), or forcing an AP into monitor/sniffer mode with a
secondary receiver. Both break normal client-serving and are not production-safe.
Cisco's supported alternative is abstracted, on-chip intelligence (CleanAir Pro, DNA
Center, Cisco Spaces) rather than raw CSI.

Consequence: raw-CSI sensing on existing Cisco hardware is not viable for a real
deployment. If body presence is used, it has to come from Cisco's abstracted presence,
which is Cisco-specific.

Sources:
- nexmon_csi framework: https://github.com/seemoo-lab/nexmon_csi
- Chipset dependency / extraction issues: https://github.com/seemoo-lab/nexmon_csi/issues/124
- CSI extraction survey: https://arxiv.org/pdf/2305.10554
- Cisco CleanAir: https://www.cisco.com/c/en/us/products/collateral/wireless/catalyst-9164-series-access-points/cleanairs-legacy.html
- Cisco DNA Center: https://www.cisco.com/c/en/us/products/collateral/cloud-systems-management/dna-center/guide-c07-744044.html

## Raw CSI or pre-processed presence from Cisco?

Cisco exposes pre-processed presence, not raw CSI. The fine amplitude/phase data used
for high-fidelity sensing is handled on-chip and not made available to developers. What
is available is abstracted location, heatmaps, and aggregate room occupancy through
Spaces/DNA, plus higher-level availability states through the collaboration APIs.

Consequence: the only supported Cisco body-presence signal is coarse and Cisco-specific
— usable for "someone is in this zone," not for anything finer, and not portable across
vendors.

Sources:
- WiFi CSI device-free sensing overview: https://www.edgeorbital.io/2026/04/07/wifi-csi-device-free-sensing-2026/
- How CSI sensing works: https://www.digitalintelligence.at/wifi-signals-can-see-you-how-csi-sensing-works/
- Cisco DNA Spaces: https://www.outcomex.com.au/news/transform-organisation-dna-spaces/

## Human-vs-object and still-body detection

Distinguishing a human from an object while moving is reliable, but the reliable systems
are camera-based computer vision, not WiFi. Detecting a completely stationary person is
the hard case: camera AI struggles without motion, and the reliable tool for a still,
breathing body is mmWave radar — dedicated extra hardware, not WiFi. PIR sensors report
a room as empty when a person sits still.

Consequence: "confirm a human sitting still in a zone" is the weakest case for WiFi and
the strongest case for mmWave hardware. Making still-body confirmation mandatory implies
extra hardware, which conflicts with the no-extra-hardware goal.

Sources:
- Still-body detection / mmWave presence sensing: https://homey.app/en-us/wiki/mmwave-vs-pir-presence-and-motion-sensors-explained/
- Presence vs motion sensors: https://www.truehomeprotection.com/presence-sensor-vs-motion-sensor/
- Human detection limits: https://arxiv.org/html/2606.03694v2

## Is there a vendor-agnostic sensing standard? (802.11bf)

IEEE 802.11bf (WLAN Sensing) is ratified and is the standardized, vendor-agnostic path
for WiFi motion/presence sensing. It standardizes how devices negotiate sensing, so a
certified sensor from one vendor can process signals from another vendor's AP. It is
built into the radio/MAC layers of newer chipsets shipping with Wi-Fi 7, and Cisco,
Aruba and Juniper are on the roadmap.

Consequence: a clean "any WiFi senses presence" capability is coming, but on new
hardware rather than the APs deployed today. It is the future path to design toward, not
a capability that can be assumed to exist now.

Sources:
- 802.11bf overview: https://medium.com/@jeromedecinco/ieee-802-11bf-the-wi-fi-standard-that-turns-networks-into-sensors-c046df0eda23
- NIST on 802.11bf: https://www.nist.gov/publications/ieee-80211bf-enabling-widespread-adoption-wi-fi-sensing
- Privacy gap discussion: https://secnora.com/blog/wi-fi-sensing-and-the-ieee-802-11bf-privacy-gap/
- Multi-vendor interoperability: https://www.cognitivesystems.com/how-does-802-11bf-enhance-legacy-sensing

---

## Person re-identification by WiFi

### Accuracy versus group size

Reported CSI person re-identification accuracy is roughly 75–92% for 2–10 subjects.
Small groups (2–6) can reach around 93%, and accuracy falls as the group grows. The
strongest numbers are all at very small scale: ~99.8% was reported for 6 people, and
~92.9% for 10. As the number of subjects rises, the difference between individuals
shrinks relative to environmental noise (multipath, layout), so classification degrades.
No results demonstrate this working beyond roughly 10 people — far below a workplace of
dozens to hundreds.

Sources:
- Wi-Gait / re-identification study: https://pmc.ncbi.nlm.nih.gov/articles/PMC7837618/
- CSI human ID with data augmentation: https://www.researchgate.net/publication/352806676_A_Deep_Learning-based_Human_Identification_System_with_Wi-Fi_CSI_Data_Augmentation
- Group-size vs accuracy: https://www.cse.unsw.edu.au/~wenh/zhang_dcoss16.pdf
- Stationary-subject identification: https://arxiv.org/html/2507.12854v1
- Survey: https://www.sciencedirect.com/science/article/abs/pii/S1389128623001962

### Why it breaks in a real office

Every one of the documented failure conditions is guaranteed to occur in a workplace:
a different room changes the RF baseline; moving furniture shifts the signal path;
changing the walking path breaks straight-line training; a coat, bag or different shoes
alters silhouette and gait; a change in walking speed distorts the CSI frequency
features; and multiple people moving at once blind the model unless complex signal
separation is applied.

Sources:
- Generalization limitations: https://ieeexplore.ieee.org/iel8/7755/11025553/10882950.pdf
- Environmental sensitivity / layout changes: https://ieeexplore.ieee.org/iel8/7755/4358975/11459360.pdf
- Clothing and carry-on problem: https://dl.acm.org/doi/10.1007/s10044-026-01727-7
- Speed variation: https://www.sciencedirect.com/science/article/pii/S0957417417306917
- Co-presence interference: https://pmc.ncbi.nlm.nih.gov/articles/PMC12115556/

### How production systems work around it

Real-world pipelines abandon raw-CSI matching. They add a hardware abstraction layer
across chipsets, extract domain-invariant features (Doppler / body-velocity profiles),
and run continual or federated learning on edge devices such as ESP32 clusters. Most
significantly, enrollment is cross-modal: a camera or fingerprint scanner, or the user's
phone auto-connecting to the network, provides the identity while WiFi records the RF
footprint.

In other words, the state-of-the-art fix for "WiFi cannot identify people" is to let a
camera, fingerprint, or login provide the identity — which is the architecture this
platform already uses. These systems are also heavy and hardware-dependent, not a cheap
in-software addition.

Sources:
- Domain adaptation / cross-modal training: https://www.mdpi.com/2079-9292/14/11/2299
- Cross-modal WiFi+vision training: https://dl.acm.org/doi/full/10.1145/3616494
- Feature/augmentation methods: https://arxiv.org/abs/2401.00964

---

## Conclusions

1. Identity comes from network login. WiFi is not used to determine who a person is.
   Login is robust, cheap, scales to any headcount, and is unaffected by clothing or
   furniture changes.
2. WiFi sensing is used only for anonymous presence — confirming a body is in a zone —
   and only where the hardware supports it. Its proven use cases (occupancy, motion,
   fall detection) are all anonymous, not per-person identity.
3. Body-presence confirmation is capability-dependent, not mandatory. On current
   hardware it implies either Cisco-specific presence or mmWave hardware, so the platform
   designs a socket for presence confirmation and enables it where available. 802.11bf is
   the path to make this vendor-agnostic in future.
4. Per-person WiFi identification is closed as a research question for this product:
   demonstrated only at small scale, fragile to environment, clothing and multi-person
   conditions, expensive, and dependent on a camera or login for enrollment even in its
   most advanced form.
