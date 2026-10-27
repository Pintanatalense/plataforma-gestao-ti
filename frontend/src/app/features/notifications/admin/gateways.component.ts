import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { Gateway, NotificationsAdminService } from '../../../core/services/notifications-admin.service';
import { CHANNEL_NAMES } from './channels.component';

export const FORMATTING_LABELS: Record<string, string> = {
  plain: 'Texto simples',
  html: 'HTML (e-mail)',
  whatsapp: 'Texto com *negrito* do WhatsApp',
  slack: 'Texto com formatação do Slack'
};

/** Recursos de um canal para exibição, na ordem da tela; só o que a integração faz de verdade. */
export function featureList(g: Gateway): { label: string; on: boolean }[] {
  const c = g.capabilities;
  return [
    { label: 'Recebe mensagens', on: c.inbound },
    { label: 'Confirma entrega', on: c.delivery_receipts },
    { label: 'Confirma leitura', on: c.read_receipts },
    { label: 'Anexos', on: c.attachments },
    { label: '"Digitando…"', on: c.typing }
  ];
}

@Component({
  selector: 'app-gateways',
  standalone: true,
  imports: [FormsModule, RouterLink, MatButtonModule, MatFormFieldModule, MatInputModule, MatSnackBarModule],
  template: `
    <p class="intro">
      O que cada canal faz hoje nesta instalação e o ritmo de envio. O limite só pode ser <strong>reduzido</strong>
      abaixo do máximo do canal. Para conectar ou configurar um canal, use
      <a routerLink="/channels">Canais de comunicação</a>.
    </p>

    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }

    <div class="cards">
      @for (g of items(); track g.channel) {
        <section class="card" data-testid="gateway-card">
          <header>
            <h3>{{ name(g.channel) }}</h3>
            <span class="state" [class.on]="g.enabled" data-testid="gateway-state">
              {{ g.enabled ? 'Ligado' : (g.configured ? 'Desligado' : 'Não configurado') }}
            </span>
          </header>
          @if (g.provider) {
            <p class="muted">Provedor: {{ g.provider === 'evolution' ? 'Evolution API' : 'Meta Cloud API' }}</p>
          }
          <p><strong>Formato:</strong> {{ formatting(g.capabilities.formatting) }}
            @if (g.capabilities.max_len) { · até {{ g.capabilities.max_len }} caracteres }
          </p>
          <ul class="features">
            @for (f of features(g); track f.label) {
              <li [class.on]="f.on">{{ f.on ? '✓' : '—' }} {{ f.label }}</li>
            }
          </ul>

          @if (g.limits.ceiling_rate_per_second !== null) {
            <div class="limit">
              <p>
                <strong>Ritmo:</strong> {{ g.limits.effective_rate_per_second }} envio(s)/s
                (máximo do canal: {{ g.limits.ceiling_rate_per_second }})
              </p>
              @if (g.configured) {
                <mat-form-field appearance="outline" subscriptSizing="dynamic">
                  <mat-label>Novo limite (envios/s)</mat-label>
                  <input matInput type="number" min="0.01" [max]="g.limits.ceiling_rate_per_second" step="0.1"
                         [(ngModel)]="draft[g.channel]" data-testid="limit-input" />
                </mat-form-field>
                <button mat-stroked-button (click)="save(g)" [disabled]="busy()" data-testid="limit-save">Salvar</button>
                @if (g.limits.rate_per_second !== null) {
                  <button mat-button (click)="reset(g)" [disabled]="busy()" data-testid="limit-reset">Voltar ao máximo</button>
                }
              }
            </div>
          } @else {
            <p class="muted">Sem limite de envio (canal local).</p>
          }

          @if (g.limits.max_per_hour_per_person !== undefined) {
            <p class="muted" data-testid="wa-limits">
              Contra banimento: {{ g.limits.send_interval_seconds }} s entre envios e até
              {{ g.limits.max_per_hour_per_person }} mensagem(ns) por pessoa por hora (ajuste na aba WhatsApp).
            </p>
          }
        </section>
      }
    </div>
  `,
  styles: [`
    .intro { margin: 16px 0; color: #475569; font-size: 14px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
    .card { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; background: #fff; font-size: 14px; }
    .card header { display: flex; justify-content: space-between; align-items: center; }
    .card h3 { margin: 0; font-size: 16px; }
    .state { font-size: 12px; padding: 2px 8px; border-radius: 12px; background: #e2e8f0; }
    .state.on { background: #dcfce7; }
    .features { list-style: none; padding: 0; margin: 8px 0; color: #94a3b8; }
    .features li.on { color: #166534; }
    .limit { border-top: 1px solid #f1f5f9; padding-top: 8px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .limit p { flex-basis: 100%; margin: 0; }
    .muted { color: #64748b; font-size: 13px; }
    .error { color: #dc2626; }
  `]
})
export class GatewaysComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);

  items = signal<Gateway[]>([]);
  error = signal('');
  busy = signal(false);
  draft: Record<string, number | null> = {};

  ngOnInit(): void {
    this.load();
  }

  name(channel: string): string {
    return CHANNEL_NAMES[channel] ?? channel;
  }

  formatting(value: string): string {
    return FORMATTING_LABELS[value] ?? value;
  }

  features(g: Gateway) {
    return featureList(g);
  }

  load(): void {
    this.api.listGateways().subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.draft = Object.fromEntries(res.items.map((g) => [g.channel, g.limits.rate_per_second]));
      },
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível carregar os gateways.'))
    });
  }

  save(g: Gateway): void {
    const value = this.draft[g.channel];
    if (value === null || value === undefined || !(value > 0)) {
      this.error.set('Informe um limite maior que zero.');
      return;
    }
    this.apply(g, Number(value));
  }

  reset(g: Gateway): void {
    this.apply(g, null);
  }

  private apply(g: Gateway, value: number | null): void {
    this.error.set('');
    this.busy.set(true);
    this.api.updateGatewayLimit(g.channel, value).subscribe({
      next: (updated) => {
        this.busy.set(false);
        this.items.update((list) => list.map((item) => (item.channel === updated.channel ? updated : item)));
        this.draft[g.channel] = updated.limits.rate_per_second;
        this.snack.open('Limite atualizado.', 'OK', { duration: 3000 });
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiErrorMessage(err, 'Não foi possível salvar o limite.'));
      }
    });
  }
}
