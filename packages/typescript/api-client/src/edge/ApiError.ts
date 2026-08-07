import type { Problem } from "./types";

/**
 * Raised for non-2xx API responses. `problem` is populated when the server
 * returned an `application/problem+json` body (contract 05).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: Problem | null;

  constructor(status: number, code: string, message: string, problem: Problem | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.problem = problem;
  }
}
