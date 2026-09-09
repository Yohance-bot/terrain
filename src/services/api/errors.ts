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

export function accountErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const detail=(error.body as {detail?:unknown})?.detail;
    if (typeof detail==='string') return detail;
    if (error.status === 401) return 'Username or password is incorrect. Please try again.';
    if (error.status === 403) return 'This sign-in is unavailable. Check your account access.';
    if (error.status === 404) return 'The account service was not found. Check the configured backend URL and account settings.';
    if (error.status === 422) return 'Check your username and use a password of at least 12 characters when creating an account.';
    if (error.status >= 500) return `The server returned an error (${error.status}). Please try again shortly.`;
    return `Sign-in was rejected (${error.status}). Please try again.`;
  }
  if (error instanceof Error && /timed out/i.test(error.message)) {
    return 'The server took too long to respond. It may be waking up. Please try again.';
  }
  if (error instanceof Error && /Google|sign-in.*expired/i.test(error.message)) return error.message;
  return 'Could not reach the cloud server. Check your internet connection and try again.';
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
    if (error.status === 422) {
      return 'Run ended, but could not be processed by the server.';
    }
    if (error.status >= 400 && error.status < 500) {
      return 'Run ended, but was not accepted by the server.';
    }
    return 'Run saved on device. Submission failed — will retry automatically.';
  }

  return 'Run saved on device and queued for submission.';
}
