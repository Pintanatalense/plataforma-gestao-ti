// Configuração extra do Vitest, lida pelo builder `@angular/build:unit-test` (`runnerConfig: true` no angular.json).
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // O 1º teste de cada arquivo compila o componente e o Angular Material na hora (0,3–2 s numa máquina livre).
    // Com a máquina ocupada (CI local rodando o backend, Docker), isso passava dos 5 s padrão e o teste falhava por
    // tempo, sem defeito. 15 s ainda pega teste preso; tempo real de espera (timer de snackbar etc.) deve ser
    // evitado no próprio teste, não coberto por este limite.
    testTimeout: 15_000,
  },
});
