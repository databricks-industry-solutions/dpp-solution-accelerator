Copyright (2025) Databricks, Inc.

This Software includes software developed at Databricks (https://www.databricks.com/) and its use is subject to the included LICENSE file.
By using this repository and the assets within, you consent to Databricks collection and use of usage and tracking information in accordance with our privacy policy at www.databricks/privacypolicy.

--------------------------------------------------------------------------------
Synthetic data
--------------------------------------------------------------------------------
This repository ships NO external or customer datasets. All demo data is
SYNTHETIC and generated at deploy time — nothing is committed to the repo
(src/foundation/data/ is git-ignored).

How it is generated:
- src/foundation/02_synthetic_data_generator.py produces deterministic synthetic
  records (fixed seed) with the Faker library for a fictional manufacturer
  ("NordicForm AB", furniture) or a fictional battery maker ("VoltCore Energy AB"),
  selected via the --profile flag. Both companies and all products, suppliers,
  certificates, and identifiers are entirely fictional.
- The generation code is in this repository and uses an open-source library
  (Faker, MIT License). No proprietary or third-party data is used.

--------------------------------------------------------------------------------
AI-generated content
--------------------------------------------------------------------------------
- The optional pre-computed insights (src/pipelines/gold/precompute_insights.py)
  call a Databricks Foundation Model serving endpoint via ai_query at run time.
  No AI-generated content is committed to this repository.

--------------------------------------------------------------------------------
Third-party components
--------------------------------------------------------------------------------
See the "Dependencies and licenses" section of README.md for the list of
third-party libraries used and their licenses.
