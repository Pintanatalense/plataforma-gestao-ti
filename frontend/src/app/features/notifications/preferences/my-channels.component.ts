import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ChannelLinkInfo, LinkCode, NotificationsService } from '../../../core/services/notifications.service';

/** Minutos restantes (arredondado para cima) até `expiresAt`; 0 quando já expirou. */
export function minutesLeft(expiresAt: string, now: number = Date.now()): number {
  const ms = new Date(expiresAt).getTime() - now;
  return ms > 0 ? Math.ceil(ms / 60_000) : 0;
}

@Component({
  selector: 'app-my-channels',
  standalone: true,
  imports: [CommonModule, DatePipe, MatButtonModule, MatIconModule, MatSnackBarModule],
  template: `
    <section class="card" data-testid="my-channels">
      <h2>Meus canais</h2>
      @for (c of channels(); track c.channel) {
        <div class="channel" [attr.data-testid]="'channel-' + c.channel">
          <div class="head">
            <mat-icon>send</mat-icon>
            <strong>{{ c.label }}</strong>
            <span class="badge" [class.on]="c.linked">{{ c.linked ? 'Vinculado' : 'Não vinculado' }}</span>
          </div>

          @if (!c.available) {
            <p class="hint">Este canal ainda não foi habilitado pela administração.</p>
          } @else if (c.linked) {
            <p class="hint">Vinculado em {{ c.linked_at | date: 'dd/MM/yyyy HH:mm' }}. Você recebe avisos e pode abrir e responder chamados pelo bot.</p>
            <div><button mat-stroked-button (click)="unlink(c)" data-testid="unlink">Desvincular</button></div>
          } @else {
            @if (code(); as k) {
              <div class="code-box" data-testid="code-box">
                <p>Envie esta mensagem ao bot{{ c.bot_username ? ' @' + c.bot_username : '' }} em até {{ minutes() }} min:</p>
                <code class="code" data-testid="code-command">{{ k.command }}</code>
                @if (k.deep_link) {
                  <p><a [href]="k.deep_link" target="_blank" rel="noopener noreferrer">Ou abra o bot já com o código</a></p>
                }
                <p class="hint">O código vale uma vez. Depois de enviar, atualize esta página.</p>
              </div>
            }
            <div class="actions">
              <button mat-flat-button color="primary" (click)="generate(c)" data-testid="generate">
                {{ code() ? 'Gerar outro código' : 'Gerar código de vínculo' }}
              </button>
              @if (code()) {
                <button mat-button (click)="refresh()">Já enviei</button>
              }
            </div>
          }
        </div>
      }
      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }
    </section>
  `,
  styles: [`
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 16px; background: #fff; }
    h2 { font-size: 16px; margin: 0 0 8px; }
    .channel { display: flex; flex-direction: column; gap: 8px; }
    .head { display: flex; align-items: center; gap: 8px; }
    .badge { margin-left: auto; padding: 2px 10px; border-radius: 12px; font-size: 12px; background: #e2e8f0; }
    .badge.on { background: #dcfce7; }
    .code-box { background: #f8fafc; border: 1px dashed #94a3b8; border-radius: 8px; padding: 12px; }
    .code { display: inline-block; font-size: 20px; letter-spacing: 1px; padding: 6px 10px; background: #fff; border-radius: 4px; user-select: all; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .hint { color: #64748b; font-size: 13px; margin: 0; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class MyChannelsComponent implements OnInit {
  private service = inject(NotificationsService);
  private snack = inject(MatSnackBar);

  channels = signal<ChannelLinkInfo[]>([]);
  code = signal<LinkCode | null>(null);
  minutes = signal(0);
  error = signal('');

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.service.myChannels().subscribe({
      next: (res) => {
        this.channels.set(res.channels);
        if (res.channels.some((c) => c.linked)) this.code.set(null);
      },
      error: () => this.error.set('Não foi possível carregar seus canais.')
    });
  }

  generate(channel: ChannelLinkInfo): void {
    this.error.set('');
    this.service.createLinkCode(channel.channel).subscribe({
      next: (k) => {
        this.code.set(k);
        this.minutes.set(minutesLeft(k.expires_at));
      },
      error: (err) => this.error.set(err?.error?.error?.message ?? 'Não foi possível gerar o código.')
    });
  }

  unlink(channel: ChannelLinkInfo): void {
    if (!confirm(`Desvincular o ${channel.label}? Você deixa de receber avisos por ele.`)) return;
    this.service.unlinkChannel(channel.channel).subscribe({
      next: () => {
        this.snack.open('Canal desvinculado.', 'OK', { duration: 3000 });
        this.refresh();
      },
      error: () => this.error.set('Não foi possível desvincular.')
    });
  }
}
