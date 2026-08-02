# Miki public-resource repository rules

- This repository contains only publicly distributable resources and their build tools for 【杨】Miki.
- Keep runtime catalog files under `public-resources/`.
- Preserve attribution, license and source-commit information for every imported pack.
- Never store user data, credentials, tokens, Firebase service accounts, CloudBase SecretId/SecretKey, or private asset packs here.
- Do not store DYL, DYL fallback, or ZH2000 card bodies, chunks, media, manifests, or access credentials in this repository.
- DYL and ZH2000 remain on the existing private Tencent CloudBase/COS asset-pack path.
- Changes to public pack paths or IDs must remain backward compatible with installed Miki profiles.
