# @quant-shared

TypeScript types and constants shared between the web app (and, eventually,
generated API clients). Currently imported via the path alias
`@quant-shared/*` configured in `apps/web/tsconfig.json`.

When the API has a stable OpenAPI spec, generate matching TS types here with
`openapi-typescript`.
