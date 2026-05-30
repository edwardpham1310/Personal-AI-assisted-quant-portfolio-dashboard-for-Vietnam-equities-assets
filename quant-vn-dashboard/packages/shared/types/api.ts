/** Standard error body returned by the FastAPI app. */
export type ApiError = {
  detail: string;
};

/** Liveness response from GET /health. */
export type HealthResponse = {
  status: "ok";
  env: "development" | "staging" | "production";
  version: string;
};

/** Generic "not yet implemented" body returned by placeholder routes. */
export type NotImplementedResponse = {
  status: "not_implemented";
  module: string;
  message: string;
};
