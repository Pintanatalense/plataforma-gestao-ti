import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { MessagesService, OutboundMessage, OutboundMessageDetail } from '../../../core/services/messages.service';
import { CHANNEL_NAMES } from '../admin/channels.component';
import { PROVIDER_STATUS_LABELS, STATUS_LABELS } from '../admin/deliveries.component';
import { OUTCOME_LABELS } from './compose.component';

const PAGE_SIZE = 25;
const KIND_LABELS: Record<string, string> = { manual: 'Envio', test: 'Teste', scheduled: 'Agendado' };

/** Resumo das entregas de um envio, na ordem em que interessa ler. */
export function deliverySummary(counts: Record<string, number>): string {
  const order = ['PENDING', 'SENDING', 'SENT', 'DEAD', 'CANCELLED', 'SKIPPED'];
  return order.filter((s) => counts[s]).map((s) => `${counts[s]} ${STATUS_LABELS[s].toLowerCase()}`).join(' · ') || '—';
}

@Component({
  selector: 'app-message-history',
  standalone: true,
  imports: [DatePipe, MatButtonModule, MatSnackBarModule],
  template: `
    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }
    <div class="table-wrap">
      <table class="grid" data-testid="history-table">
        <thead><tr><th>Quando</th><th>Assunto</th><th>Canal</th><th>Tipo</th><th>Entregas</th><th></th></tr></thead>
        <tbody>
          @for (m of items(); track m.id) {
            <tr (click)="open(m)" [class.selected]="detail()?.id === m.id" data-testid="history-row">
              <td>{{ m.created_at | date: 'dd/MM HH:mm' }}</td>
              <td>{{ m.subject || '(sem assunto)' }}</td>
              <td>{{ channelName(m.channel) }}</td>
              <td>{{ kindLabel(m.kind) }}{{ m.status === 'CANCELLED' ? ' (cancelado)' : '' }}</td>
              <td>{{ summary(m) }}</td>
              <td class="row-actions">
                @if (m.status !== 'CANCELLED' && m.deliveries['PENDING']) {
                  <button mat-button (click)="cancel(m, $event)" data-testid="history-cancel">Cancelar pendentes</button>
                }
              </td>
            </tr>
          } @empty {
            <tr><td colspan="6" class="empty">Nenhum envio ainda.</td></tr>
          }
        </tbody>
      </table>
    </div>
    <div class="pager">
      <span>{{ total() }} envio(s)</span>
      <button mat-button (click)="page(-1)" [disabled]="offset() === 0">Anterior</button>
      <button mat-button (click)="page(1)" [disabled]="offset() + items().length >= total()">Próxima</button>
    </div>

    @if (detail(); as d) {
      <section class="detail" data-testid="history-detail">
        <h3>{{ d.subject || '(sem assunto)' }}</h3>
        <pre>{{ d.body }}</pre>
        <h4>Destinatários</h4>
        <ul>
          @for (r of d.recipients; track r.user_id) {
            <li>
              {{ r.name || r.email }}:
              @if (r.delivery; as del) {
                {{ statusLabel(del.status) }}{{ del.provider_status ? ' · ' + providerLabel(del.provider_status) : '' }}
                {{ del.last_error ? ' — ' + del.last_error : '' }}
              } @else {
                {{ outcomeLabel(r.outcome) }}
              }
            </li>
          }
        </ul>
      </section>
    }
  `,
  styles: [`
    .table-wrap { overflow-x: auto; margin-top: 16px; }
    .grid { width: 100%; border-collapse: collapse; font-size: 13px; }
    .grid th { text-align: left; padding: 8px; border-bottom: 2px solid #e2e8f0; color: #475569; }
    .grid td { padding: 8px; border-bottom: 1px solid #f1f5f9; }
    .grid tbody tr { cursor: pointer; }
    .grid tbody tr:hover, .grid tr.selected { background: #f8fafc; }
    .row-actions { text-align: right; white-space: nowrap; }
    .pager { display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 8px; }
    .pager span { margin-right: auto; color: #64748b; }
    .detail { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-top: 16px; background: #fff; }
    .detail pre { white-space: pre-wrap; background: #f8fafc; padding: 8px; border-radius: 4px; }
    .empty { text-align: center; color: #94a3b8; padding: 24px; }
    .error { color: #dc2626; }
  `]
})
export class MessageHistoryComponent implements OnInit {
  private api = inject(MessagesService);
  private snack = inject(MatSnackBar);

  items = signal<OutboundMessage[]>([]);
  total = signal(0);
  offset = signal(0);
  detail = signal<OutboundMessageDetail | null>(null);
  error = signal('');

  ngOnInit(): void {
    this.load();
  }

  channelName(channel: string): string {
    return CHANNEL_NAMES[channel] ?? channel;
  }

  statusLabel(status: string): string {
    return STATUS_LABELS[status] ?? status;
  }

  providerLabel(status: string): string {
    return PROVIDER_STATUS_LABELS[status] ?? status;
  }

  outcomeLabel(outcome: string): string {
    return OUTCOME_LABELS[outcome] ?? outcome;
  }

  kindLabel(kind: string): string {
    return KIND_LABELS[kind] ?? kind;
  }

  summary(m: OutboundMessage): string {
    return deliverySummary(m.deliveries);
  }

  page(direction: number): void {
    this.offset.update((o) => Math.max(0, o + direction * PAGE_SIZE));
    this.load();
  }

  load(): void {
    this.error.set('');
    this.api.list({ limit: PAGE_SIZE, offset: this.offset() }).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.total.set(res.total);
      },
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível carregar o histórico.'))
    });
  }

  open(m: OutboundMessage): void {
    this.api.get(m.id).subscribe({ next: (d) => this.detail.set(d) });
  }

  cancel(m: OutboundMessage, event: Event): void {
    event.stopPropagation();
    this.api.cancel(m.id).subscribe({
      next: (res) => {
        this.snack.open(`${res.cancelled} entrega(s) cancelada(s).`, 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => this.snack.open(apiErrorMessage(err, 'Não foi possível cancelar.'), 'OK', { duration: 4000 })
    });
  }
}
