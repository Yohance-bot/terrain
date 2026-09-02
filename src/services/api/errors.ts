/**
 * Structured API failures for development diagnostics.
 *
 * Validation rules and retry semantics stay unchanged; this module only makes
 * server rejection payloads easier to inspect during local development.
 */

export class ApiRequestError extends Error {
  readonly status: number;
  readonly method: string;
  readonly path: string;
  readonly bodyText: string;
  readonly body: unknown;

  constructor(method: string, path: string, status: number, bodyText: string) {
    super(`${method} ${path} failed (${status}): ${bodyText}`);
    this.name = 'ApiRequestError';
    this.status = status;
    this.method = method;
    this.path = path;
    this.bodyText = bodyText;
    this.body = parseResponseBody(bodyText);
  }
}

function parseResponseBody(bodyText: string): unknown {
  if (!bodyText) return null;
  try {
    return JSON.parse(bodyText) as unknown;
  } catch {
    return bodyText;
  }
}

function formatValidationBody(body: unknown): string {
  if (body == null) return '(empty response body)';
  if (typeof body === 'string') return body;
  return JSON.stringify(body, null, 2);
}

/** Log the full rejection payload to Metro / device logs in development builds. */
export function logApiRequestErrorInDev(error: unknown, context: string): void {
  if (!__DEV__) return;

  if (error instanceof ApiRequestError) {
    console.log(`[run/api] ${context}`, {
      method: error.method,
      path: error.path,
      status: error.status,
      bodyText: error.bodyText,
      body: error.body,
      validationDetail: formatValidationBody(error.body),
    });
    return;
  }

  console.log(`[run/api] ${context}`, error);
}

export function queuedRunNotice(error?: unknown): string {
  if (error instanceof ApiRequestError) {
    return 'Run saved on device. The server rejected it for now — it will retry automatically.';
  }

  return 'Run saved on device and queued for submission.';
}
