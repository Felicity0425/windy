# CMA independence report

## Evidence

- Product page: `https://data.cma.cn/data/detail/dataCode/NAFP_CRA40_FTM_6HOR.html`
- Product page wording:
  - Title: `中国第一代全球大气再分析产品（CMA-RA）-逐6小时产品`
  - Description: `同化方法为三维变分`
- Manual URL: `https://data.cma.cn/article/showPDFFile.html?file=/pic/static/doc/cra/%E4%B8%AD%E5%9B%BD%E6%B0%94%E8%B1%A1%E5%B1%80%E5%85%A8%E7%90%83%E5%A4%A7%E6%B0%94%EF%BC%8F%E9%99%86%E9%9D%A2%E5%86%8D%E5%88%86%E6%9E%90%E4%BA%A7%E5%93%81%EF%BC%88CMA-RA%EF%BC%89%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.pdf`
- Manual revision date: `2022-04-25`
- Manual wording: CMA-RA is a reanalysis product family built from observations, numerical modeling, and data assimilation.
- Manual file-naming rule: `CRA40_[...]_V1_[产品类型].grib2`, where `0_0` means analysis product.
- Local files: `CRA40_*_GLB_34KM_HOUR_V1_0_0.grib2?...&dataCode=NAFP_CRA40_FTM_6HOR...`, covering `2026-01-23 00Z` to `2026-02-24 00Z`.

## What This Proves

- `NAFP_CRA40_FTM_6HOR` is an official CMA-RA reanalysis product page, not a pure forecast page.
- The page itself explicitly states a 3DVAR assimilation method.
- The local filenames match the manual's `0_0 = analysis product` convention.

## What This Does Not Prove

- The page does not explicitly state whether the 2026 `FTM` production stream excludes the same aircraft winds used in this project's strict holdout.
- Therefore it does not prove `background_independent_of_holdout = true`.

## Conclusion

- `P0-LEAK` is only partially satisfied:
  - `forecast vs reanalysis` has been resolved in favor of `reanalysis / analysis product`.
  - `independent of strict-holdout aircraft winds` remains unproven.
- `S4-CMA-M1` display-only fill is safe because official `recon_u/v/conf/mask` and strict holdout metrics remain untouched.
- `S4-OI-*`, innovation diagnostics, and Desroziers-style statistics remain blocked unless CMA confirms this background is independent of the strict-holdout aircraft winds, or we switch to a demonstrably independent forecast background.
- Working assumption for this demo remains `background_independent_of_holdout = false` for OI-grade claims, but acceptable for M1 product-only usage.
