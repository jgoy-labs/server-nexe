# Model catalog channel — please do not delete this branch

**`catalog-bootstrap` is a live production channel, not a stale branch.**

The file [`catalog.json`](./catalog.json) on this branch is the remote model
catalog that the **nexe-app desktop onboarding wizard** fetches at runtime to
list the models a user can install.

- **Consumed by:** `nexe-app` → `src-tauri/src/catalog.rs` → `fetch_catalog()`,
  via `https://raw.githubusercontent.com/jgoy-labs/server-nexe/catalog-bootstrap/docs/catalog.json`
  (5-second timeout).
- **If this branch is deleted:** the app does **not** crash — it falls back to
  the catalog embedded in each binary — but **remote catalog updates stop
  working** for every client that is already installed.
- **Keep in sync:** `catalog.json` here is a manual mirror of the source of
  truth in `installer/installer_catalog_data.py` on `main`. Update it on this
  branch whenever the model list changes on `main`.

Please keep this branch alive while released clients still point to it. To
retire it cleanly, first move the manifest to `main`, repoint `MANIFEST_URL`
in `nexe-app`, ship a new release, and only then remove the branch once no
released client depends on this URL.
