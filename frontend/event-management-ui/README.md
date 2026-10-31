# ConnectSphere frontend

From this directory, `npm ci` installs UI dependencies; `npm run dev` starts Vite
on port 5174, not the backend. Configure `.env` from `.env.example` without
overwriting existing settings. Backend startup and environment prerequisites are
in [the service directory](../../INDEX.md#running-everything-locally).

`npm run test:coverage`, `npm run lint` and `npm run build` run the UI checks.
`npm test` runs the unit/component tests beside application code in `src/`.
The mocked browser suite and unused lifecycle helper/tests were retired, not
replaced; these checks do not prove browser journeys. Playwright remains a
dependency for the existing standalone Venue Booking browser verifier, not a
frontend CI browser gate. Manual real-stack journeys and their prerequisites are
listed in [journey traceability](../../e2e/journeys/TRACEABILITY.md).

## Vite template reference

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.
