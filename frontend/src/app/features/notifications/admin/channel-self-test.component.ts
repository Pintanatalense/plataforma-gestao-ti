import { Component, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { NotificationsAdminService } from '../../../core/services/notifications-admin.service';
import { apiErrorMessage } from './rules.component';

/** "Enviar teste para mim": manda uma mensagem agora para a conta da própria pessoa no canal (Telegram ou Slack). */
@Component({
  selector: 'app-channel-self-test',
  standalone: true,
  imports: [MatButtonModule],
  template: `
    <div class="box" data-testid="self-test">
      <strong>Enviar teste</strong>
      <span class="hint">
        Manda uma mensagem agora para a <em>sua</em> conta neste canal (salve antes). Se ainda não vinculou, faça em
        Notificações &gt; Minhas preferências. Até 5 testes por hora.
      </span>
      <div class="footer">
        <button mat-stroked-button (click)="send()" [disabled]="sending()" data-testid="self-test-send">Enviar teste para mim</button>
      </div>
      @if (result(); as r) {
        <span [class.ok]="r.ok" [class.error]="!r.ok" data-testid="self-test-result">{{ r.detail }}</span>
      }
    </div>
  `,
  styles: [`
    .box { display: flex; flex-direction: column; gap: 4px; background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 8px; padding: 12px; font-size: 13px; overflow-wrap: anywhere; }
    .hint { color: #64748b; }
    .footer { display: flex; justify-content: flex-start; }
    .ok { color: #166534; font-weight: 500; }
    .error { color: #dc2626; }
  `]
})
export class ChannelSelfTestComponent {
  private api = inject(NotificationsAdminService);

  channel = input.required<'telegram' | 'slack'>();
  sending = signal(false);
  result = signal<{ ok: boolean; detail: string } | null>(null);

  send(): void {
    this.sending.set(true);
    this.result.set(null);
    this.api.testSendToMyself(this.channel()).subscribe({
      next: (r) => {
        this.sending.set(false);
        this.result.set(r);
      },
      error: (err) => {
        this.sending.set(false);
        this.result.set({ ok: false, detail: apiErrorMessage(err, 'Não foi possível enviar o teste.') });
      }
    });
  }
}
