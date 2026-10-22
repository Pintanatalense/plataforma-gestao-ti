import { apiErrorMessage } from './api-error';

const env = (status: number, message?: string, details?: unknown) => ({
  status,
  error: { error: { code: 'X', message, details } }
});

describe('apiErrorMessage', () => {
  it('uses the message of the API error envelope for 4xx', () => {
    expect(apiErrorMessage(env(409, 'Código já existe'), 'fallback')).toBe('Código já existe');
  });

  it('joins validation details (422) and strips the pydantic prefix', () => {
    const err = env(422, 'Validation error', [{ msg: 'Value error, A' }, { msg: 'B' }]);
    expect(apiErrorMessage(err, 'fallback')).toBe('A B');
  });

  it('reports a lost connection (status 0) instead of the generic fallback', () => {
    expect(apiErrorMessage({ status: 0, error: new ProgressEvent('error') }, 'fallback')).toMatch(/Sem conexão/);
  });

  it('does not show the raw message of a 5xx, only a friendly one', () => {
    const msg = apiErrorMessage(env(500, 'Traceback: boom'), 'fallback');
    expect(msg).toMatch(/servidor não conseguiu/);
    expect(msg).not.toContain('Traceback');
  });

  it('explains 403 and 429 when the server sent no message', () => {
    expect(apiErrorMessage({ status: 403 }, 'f')).toMatch(/permissão/);
    expect(apiErrorMessage({ status: 429 }, 'f')).toMatch(/Muitas tentativas/);
  });

  it('prefers the server message over the default text for 403', () => {
    expect(apiErrorMessage(env(403, "Permissão 'x.y' necessária"), 'f')).toBe("Permissão 'x.y' necessária");
  });

  it('falls back when there is nothing to say', () => {
    expect(apiErrorMessage({}, 'fallback')).toBe('fallback');
    expect(apiErrorMessage(null, 'fallback')).toBe('fallback');
    expect(apiErrorMessage({ status: 404 }, 'fallback')).toBe('fallback');
  });

  it('ignores the legacy detail field (the API never sends it)', () => {
    expect(apiErrorMessage({ status: 400, error: { detail: 'x' } }, 'fallback')).toBe('fallback');
  });
});
