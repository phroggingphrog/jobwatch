# Occupation reference provenance

This product includes information from the O*NET 31.0 Database by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), used under the [CC BY 4.0 licence](https://www.onetcenter.org/license_db.html). O*NET® is a trademark of USDOL/ETA. Jobwatch has modified the data; USDOL/ETA has not approved, endorsed, or tested these modifications.

Australian occupation titles and correspondence: Australian Bureau of Statistics, ANZSCO 2022 Australian Update (structure revised June 2023), [release and download page](https://www.abs.gov.au/statistics/classifications/anzsco-australian-and-new-zealand-standard-classification-occupations/2022), [CC BY 4.0 terms](https://www.abs.gov.au/website-privacy-copyright-and-disclaimer). This deliberately pins ANZSCO 2022; it is not a claim that ANZSCO is Australia's latest classification.

The crosswalk is also hosted under the [O*NET Resource Center content licence](https://www.onetcenter.org/license.html).

The [O*NET ESCO crosswalk](https://www.onetcenter.org/crosswalks.html) connects ESCO/ISCO codes to O*NET-SOC 2019. Jobwatch joins its ISCO unit groups to the ABS ISCO-08 correspondence. The result is many-to-many and can be broad; it does not establish equivalent qualifications or an individual job's requirements.

`source-manifest.json` records seven downloaded files, exact URLs, byte counts and SHA-256 hashes. No candidate information is included. `tools/build_occupation_reference.py` rebuilds this export offline after verifying every source hash. The source directory must contain these downloads and an identical manifest. Source metadata is also embedded in the export. Rebuild output is byte deterministic.

Derivation: occupation DWA weight is the fraction of linked O*NET occupations carrying that activity, multiplied by one plus their mean core-task fraction. GWA importance averages available, unsuppressed IM ratings; missing ratings remain absent. Repeated ESCO paths are deduplicated before averaging. Jobwatch target-family annotations are explicit local policy mappings, not official classifications. Program eligibility and level remain agent/hard-gate decisions. The fixed 60/40 coverage/cosine blend is a design choice, not a calibrated outcome model.

Local lexical retrieval proposes at most three links per skill/achievement using distinct-term TF-IDF cosine >=0.3 and at least two shared non-stopwords. These cutoffs are design choices without measured recall/precision. Proposals remain `suggested`; they cannot become confirmed recommendations automatically. Other evidence types remain available to agentic evaluation, without being treated as demonstrated activities by retrieval. A configured mapping file can supply independently reviewed links bound to exact source/reference hashes.
