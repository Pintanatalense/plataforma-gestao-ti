import { Component, OnInit, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { PushService } from '../../../core/services/push.service';

@Component({
  selector: 'app-push-settings',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatSnackBarModule],
  template: `
    <section class="card" data-testid="push-settings">
      <h2>Pop-up no navegador</h2>
      <p class="hint">
        Mostra um aviso do sistema operacional quando alguém responder seus chamados, mesmo com esta aba fechada
        (o navegador precisa estar aberto). Vale só para este navegador: ative em cada aparelho que usar.
      </p>

      @switch (push.state()) {
        @case ('unsupported') {
          <p class="warn" data-testid="push-unsupported">Este navegador não oferece notificações push.</p>
        }
        @case ('insecure') {
          <p class="warn" data-testid="push-insecure">
            As notificações só funcionam em páginas seguras. Acesse o sistema por <strong>https://</strong> ou por <strong>localhost</strong>.
          </p>
        }
        @case ('denied') {
          <p class="warn" data-testid="push-denied">
            O navegador está bloqueando as notificações deste site. Libere em <em>Configurações do site → Notificações</em> e recarregue a página.
          </p>
        }
        @case ('on') {
          <p><mat-icon class="ok">check_circle</mat-icon> Ativo neste navegador ({{ push.devices() }} {{ push.devices() === 1 ? 'aparelho' : 'aparelhos' }} na sua conta).</p>
          <div class="actions">
            <button mat-stroked-button (click)="test()" [disabled]="busy()" data-testid="push-test">Enviar teste</button>
            <button mat-button (click)="disable()" [disabled]="busy()" data-testid="push-disable">Desativar</button>
          </div>
        }
        @default {
          <div class="actions">
            <button mat-flat-button color="primary" (click)="enable()" [disabled]="busy()" data-testid="push-enable">Ativar neste navegador</button>
          </div>
        }
      }
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
    </section>
  `,
  styles: [`
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 16px; background: #fff; }
    h2 { font-size: 16px; margin: 0 0 4px; }
    .hint { color: #64748b; font-size: 13px; margin: 0; }
    .warn { background: #fef3c7; color: #92400e; border-radius: 6px; padding: 8px 12px; margin: 0; font-size: 13px; }
    .ok { color: #16a34a; vertical-align: middle; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class PushSettingsComponent implements OnInit {
  readonly push = inject(PushService);
  private snack = inject(MatSnackBar);

  busy = signal(false);
  error = signal('');

  ngOnInit(): void {
    void this.push.refresh();
  }

  private async run(action: () => Promise<unknown>, success: string, failure: string): Promise<void> {
    this.busy.set(true);
    this.error.set('');
    try {
      await action();
      this.snack.open(success, 'OK', { duration: 3000 });
    } catch (err: unknown) {
      const apiMessage = (err as { error?: { error?: { message?: string } } })?.error?.error?.message;
      this.error.set(apiMessage ?? (err instanceof Error ? err.message : failure));
    } finally {
      this.busy.set(false);
    }
  }

  enable(): Promise<void> {
    return this.run(() => this.push.enable(), 'Notificações ativadas neste navegador.', 'Não foi possível ativar.');
  }

  disable(): Promise<void> {
    return this.run(() => this.push.disable(), 'Notificações desativadas neste navegador.', 'Não foi possível desativar.');
  }

  test(): Promise<void> {
    return this.run(() => this.push.test(), 'Teste enviado; o pop-up chega em alguns segundos.', 'Não foi possível enviar o teste.');
  }
}
