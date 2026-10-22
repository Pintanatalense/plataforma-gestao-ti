/**
 * Mensagem de erro legível para uma resposta HTTP que falhou.
 *
 * Ordem: (1) mensagens de validação (422) e (2) `message` do envelope de erro da API
 * (`{ error: { code, message, details } }`, ver backend/app/core/exceptions.py), que já vêm escritas para o usuário em
 * erros 4xx; (3) texto padrão por situação (sem conexão, sem permissão, excesso de tentativas, erro do servidor);
 * (4) o texto `fallback` informado por quem chamou.
 *
 * Não lê `err.error.detail`: a API não envia esse campo (só o `message` do envelope).
 */
export function apiErrorMessage(err: unknown, fallback: string): string {
  const e = err as { status?: number; error?: { error?: { message?: string; details?: unknown }; detail?: unknown } } | null;
  const status = e?.status;

  if (status === 0) {
    return 'Sem conexão com o servidor. Verifique a rede e tente de novo.';
  }

  const body = e?.error?.error;
  if (typeof status !== 'number' || status < 500) {
    const details = body?.details;
    if (Array.isArray(details) && details.length) {
      const joined = details
        .map((d: { msg?: unknown }) => (typeof d?.msg === 'string' ? d.msg.replace(/^Value error, /, '') : ''))
        .filter(Boolean)
        .join(' ');
      if (joined) return joined;
    }
    if (typeof body?.message === 'string' && body.message) return body.message;
  }

  if (status === 403) return 'Você não tem permissão para esta ação.';
  if (status === 429) return 'Muitas tentativas em pouco tempo. Aguarde um instante e tente de novo.';
  if (typeof status === 'number' && status >= 500) {
    return 'O servidor não conseguiu concluir a operação. Tente novamente em instantes.';
  }
  return fallback;
}
