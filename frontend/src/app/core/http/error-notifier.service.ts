import { Injectable, inject } from '@angular/core';
import { Router } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';

import { AuthService } from '../auth/auth.service';

/** Intervalo mínimo entre dois avisos globais: uma tela que faz 6 chamadas não gera 6 avisos iguais. */
const NOTICE_WINDOW_MS = 5000;

/** Avisos globais de falha de comunicação e fim de sessão (usado pelo interceptor HTTP). */
@Injectable({ providedIn: 'root' })
export class ErrorNotifier {
  private snackBar = inject(MatSnackBar);
  private router = inject(Router);
  private auth = inject(AuthService);
  private lastNotice = 0;

  /** Token expirado/revogado: guarda a página atual para voltar a ela depois do login e encerra a sessão. */
  sessionEnded(): void {
    this.auth.rememberReturnUrl(this.router.url);
    this.auth.logout();
    this.show('Sua sessão expirou ou foi encerrada. Entre novamente.');
  }

  /** Servidor fora do ar (status 0) ou com erro interno (5xx). */
  serverProblem(status: number): void {
    this.show(
      status === 0
        ? 'Sem conexão com o servidor. Verifique a rede e tente de novo.'
        : 'O servidor teve um problema ao processar o pedido. Tente novamente em instantes.'
    );
  }

  private show(message: string): void {
    const now = Date.now();
    if (now - this.lastNotice < NOTICE_WINDOW_MS) return;
    this.lastNotice = now;
    this.snackBar.open(message, 'Fechar', { duration: 6000, panelClass: ['error-snackbar'] });
  }
}
